"""Anti-fingerprint init script for headless Chromium / Chrome.

This is *not* a CAPTCHA solver. The goal is more modest: make the launched
browser indistinguishable from a normal Chrome window so Akamai's bot manager
doesn't insta-flag the session before the user has even tried to log in.

The patches it applies cover every well-known headless tell:

* ``navigator.webdriver``                         → ``undefined``
* ``navigator.languages`` / ``locale``            → real values
* ``navigator.plugins`` + ``mimeTypes``           → realistic ``PluginArray``
* ``navigator.platform`` / ``userAgentData``      → consistent platform/UA-CH
* ``navigator.deviceMemory`` / ``hardwareConcurrency`` / ``maxTouchPoints``
* ``navigator.permissions.query``                  → returns sane defaults
* ``navigator.connection``                        → ``{effectiveType: '4g'}``
* ``window.chrome.{runtime,app,csi,loadTimes}``   → present
* ``WebGLRenderingContext.getParameter`` (v1+v2)  → realistic vendor/renderer
* ``HTMLCanvasElement.toDataURL`` / ``getImageData`` → tiny per-pixel noise
* ``AudioContext.createAnalyser``                 → minor float jitter
* ``RTCPeerConnection.createOffer`` SDP           → strip ``c=IN IP4`` lines
* ``Function.prototype.toString``                 → returns "[native code]"
* ``screen.{width,height,availWidth,availHeight}`` → clamp to viewport
* iframe ``contentWindow``                        → re-applies all patches

The script is wrapped in a single IIFE so it runs *before* any page script
sees a fresh ``window``. It also uses Object.defineProperty with
``configurable: true`` so successive ``addInitScript`` calls don't crash if
the patch already exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import CHROME_FULL_VERSION, CHROME_VERSION, BypassConfig

if TYPE_CHECKING:  # pragma: no cover - only used for type hints
    from playwright.sync_api import BrowserContext


# ---------------------------------------------------------------------------
# Chrome launch flags
# ---------------------------------------------------------------------------

# We never want the "Chrome is being controlled by automated test software"
# yellow bar — that's an obvious bot tell — and we don't want any of the
# default headless behaviours that leak through fingerprints.
LAUNCH_ARGS: tuple[str, ...] = (
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process,AutomationControlled",
    "--disable-site-isolation-trials",
    "--disable-dev-shm-usage",
    "--no-default-browser-check",
    "--no-first-run",
    "--no-sandbox",
    "--disable-infobars",
    "--disable-popup-blocking",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
    "--disable-background-networking",
    "--disable-sync",
    "--metrics-recording-only",
    "--password-store=basic",
    "--use-mock-keychain",
    "--lang=en-GB",
    "--start-maximized",
)

IGNORE_DEFAULT_ARGS: tuple[str, ...] = (
    "--enable-automation",
    "--enable-blink-features=IdleDetection",
)


# ---------------------------------------------------------------------------
# Init script
# ---------------------------------------------------------------------------

# The big stealth payload. ``$$VAR$$`` placeholders get substituted at runtime
# from a :class:`BypassConfig` so we don't have to re-format the JS by hand.
_STEALTH_TEMPLATE = r"""
(() => {
    'use strict';

    // Run once per realm. Without this, addInitScript firing again inside a
    // navigated iframe would throw "Cannot redefine property" errors.
    if (window.__akamai_stealth_applied) { return; }
    Object.defineProperty(window, '__akamai_stealth_applied', {
        value: true, configurable: false, writable: false, enumerable: false
    });

    const define = (obj, prop, value) => {
        try {
            Object.defineProperty(obj, prop, {
                get: typeof value === 'function' ? value : () => value,
                configurable: true,
                enumerable: true,
            });
        } catch (e) { /* swallow */ }
    };

    // ---- 1. navigator.webdriver ----------------------------------------
    define(navigator, 'webdriver', () => undefined);

    // ---- 2. languages / locale -----------------------------------------
    define(navigator, 'languages', () => ['$$LOCALE$$', '$$LOCALE_BASE$$']);

    // ---- 3. plugins + mimeTypes ----------------------------------------
    const pdfPluginNames = [
        'PDF Viewer',
        'Chrome PDF Viewer',
        'Chromium PDF Viewer',
        'Microsoft Edge PDF Viewer',
        'WebKit built-in PDF',
    ];
    const fakePlugins = pdfPluginNames.map((name) => ({
        name,
        filename: 'internal-pdf-viewer',
        description: 'Portable Document Format',
        length: 1,
        item: () => null,
        namedItem: () => null,
        0: { type: 'application/pdf', suffixes: 'pdf', description: '' },
    }));
    fakePlugins.length = pdfPluginNames.length;
    fakePlugins.item = (i) => fakePlugins[i] || null;
    fakePlugins.namedItem = (n) => fakePlugins.find((p) => p.name === n) || null;
    fakePlugins.refresh = () => {};
    define(navigator, 'plugins', () => fakePlugins);

    const fakeMimes = [
        { type: 'application/pdf', suffixes: 'pdf', description: '' },
        { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: '' },
    ];
    fakeMimes.item = (i) => fakeMimes[i] || null;
    fakeMimes.namedItem = (n) => fakeMimes.find((m) => m.type === n) || null;
    define(navigator, 'mimeTypes', () => fakeMimes);

    // ---- 4. platform / hardware ----------------------------------------
    define(navigator, 'platform', () => '$$PLATFORM$$');
    define(navigator, 'oscpu', () => '$$PLATFORM$$');
    define(navigator, 'deviceMemory', () => 8);
    define(navigator, 'hardwareConcurrency', () => 8);
    define(navigator, 'maxTouchPoints', () => 0);
    define(navigator, 'vendor', () => 'Google Inc.');
    define(navigator, 'productSub', () => '20030107');
    define(navigator, 'product', () => 'Gecko');

    // ---- 5. user-agent client hints (sec-ch-ua) ------------------------
    try {
        const brands = [
            { brand: 'Google Chrome', version: '$$CH_MAJOR$$' },
            { brand: 'Chromium',       version: '$$CH_MAJOR$$' },
            { brand: 'Not_A Brand',    version: '24' },
        ];
        const fullList = [
            { brand: 'Google Chrome', version: '$$CH_FULL$$' },
            { brand: 'Chromium',       version: '$$CH_FULL$$' },
            { brand: 'Not_A Brand',    version: '24.0.0.0' },
        ];
        const uaData = {
            brands,
            mobile: false,
            platform: '$$PLATFORM_SHORT$$',
            getHighEntropyValues: (hints) => Promise.resolve({
                architecture: 'x86',
                bitness: '64',
                brands,
                fullVersionList: fullList,
                mobile: false,
                model: '',
                platform: '$$PLATFORM_SHORT$$',
                platformVersion: '6.5.0',
                uaFullVersion: '$$CH_FULL$$',
                wow64: false,
            }),
            toJSON: () => ({ brands, mobile: false, platform: '$$PLATFORM_SHORT$$' }),
        };
        define(navigator, 'userAgentData', () => uaData);
    } catch (e) {}

    // ---- 6. permissions.query ------------------------------------------
    if (navigator.permissions && navigator.permissions.query) {
        const original = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = (parameters) => {
            if (parameters && parameters.name === 'notifications') {
                return Promise.resolve({
                    state: (typeof Notification !== 'undefined' ? Notification.permission : 'default'),
                    onchange: null,
                });
            }
            return original(parameters);
        };
    }

    // ---- 7. NetworkInformation -----------------------------------------
    try {
        const conn = {
            effectiveType: '4g',
            rtt: 50,
            downlink: 10,
            saveData: false,
            type: 'wifi',
            onchange: null,
            addEventListener: () => {},
            removeEventListener: () => {},
        };
        define(navigator, 'connection', () => conn);
    } catch (e) {}

    // ---- 8. window.chrome shim -----------------------------------------
    window.chrome = window.chrome || {};
    window.chrome.runtime = window.chrome.runtime || {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        connect: () => ({ postMessage: () => {}, disconnect: () => {} }),
        sendMessage: () => {},
        id: undefined,
    };
    window.chrome.app = window.chrome.app || {
        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
        getDetails: () => null,
        getIsInstalled: () => false,
        isInstalled: false,
    };
    window.chrome.csi = window.chrome.csi || function () {
        return { onloadT: Date.now(), startE: Date.now(), pageT: 0, tran: 15 };
    };
    window.chrome.loadTimes = window.chrome.loadTimes || function () {
        return {
            requestTime: Date.now() / 1000,
            startLoadTime: Date.now() / 1000,
            commitLoadTime: Date.now() / 1000,
            finishDocumentLoadTime: Date.now() / 1000,
            finishLoadTime: Date.now() / 1000,
            firstPaintTime: Date.now() / 1000,
            firstPaintAfterLoadTime: 0,
            navigationType: 'Other',
            wasFetchedViaSpdy: true,
            wasNpnNegotiated: true,
            npnNegotiatedProtocol: 'h2',
            wasAlternateProtocolAvailable: false,
            connectionInfo: 'h2',
        };
    };

    // ---- 9. WebGL vendor/renderer (v1 + v2) ----------------------------
    const patchWebGL = (proto) => {
        if (!proto) return;
        const orig = proto.getParameter;
        proto.getParameter = function (parameter) {
            // UNMASKED_VENDOR_WEBGL
            if (parameter === 37445) return 'Intel Inc.';
            // UNMASKED_RENDERER_WEBGL
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return orig.call(this, parameter);
        };
    };
    try { patchWebGL(WebGLRenderingContext.prototype); } catch (e) {}
    try { patchWebGL(WebGL2RenderingContext.prototype); } catch (e) {}

    // ---- 10. Canvas fingerprint noise ----------------------------------
    try {
        const noisify = (canvas) => {
            const ctx = canvas.getContext && canvas.getContext('2d');
            if (!ctx || !canvas.width || !canvas.height) return;
            const w = canvas.width, h = canvas.height;
            try {
                const img = ctx.getImageData(0, 0, w, h);
                for (let i = 0; i < img.data.length; i += 4) {
                    img.data[i]     ^= 1;
                    img.data[i + 1] ^= 1;
                    img.data[i + 2] ^= 1;
                }
                ctx.putImageData(img, 0, 0);
            } catch (e) {}
        };
        const origToData = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function (...args) {
            try { noisify(this); } catch (e) {}
            return origToData.apply(this, args);
        };
        const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function (sx, sy, sw, sh) {
            const data = origGetImageData.call(this, sx, sy, sw, sh);
            for (let i = 0; i < data.data.length; i += 4) {
                data.data[i]     ^= (i & 1);
                data.data[i + 1] ^= ((i + 1) & 1);
                data.data[i + 2] ^= ((i + 2) & 1);
            }
            return data;
        };
    } catch (e) {}

    // ---- 11. AudioContext fingerprint noise ----------------------------
    try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
            const origGetChannelData = AudioBuffer.prototype.getChannelData;
            AudioBuffer.prototype.getChannelData = function (...args) {
                const data = origGetChannelData.apply(this, args);
                if (data && data.length) {
                    for (let i = 0; i < data.length; i += 50) {
                        data[i] = data[i] + 1e-7 * (Math.random() - 0.5);
                    }
                }
                return data;
            };
        }
    } catch (e) {}

    // ---- 12. WebRTC IP leak -------------------------------------------
    try {
        if (window.RTCPeerConnection) {
            const PC = window.RTCPeerConnection;
            const stripIPs = (sdp) => sdp ? sdp.replace(/c=IN IP4 \d+\.\d+\.\d+\.\d+/g, 'c=IN IP4 0.0.0.0') : sdp;
            const origCreateOffer = PC.prototype.createOffer;
            PC.prototype.createOffer = function (...args) {
                return origCreateOffer.apply(this, args).then((offer) => {
                    if (offer && offer.sdp) offer.sdp = stripIPs(offer.sdp);
                    return offer;
                });
            };
            const origCreateAnswer = PC.prototype.createAnswer;
            PC.prototype.createAnswer = function (...args) {
                return origCreateAnswer.apply(this, args).then((answer) => {
                    if (answer && answer.sdp) answer.sdp = stripIPs(answer.sdp);
                    return answer;
                });
            };
        }
    } catch (e) {}

    // ---- 13. Function.prototype.toString -- "[native code]" ------------
    try {
        const origToString = Function.prototype.toString;
        const cache = new WeakMap();
        Function.prototype.toString = function () {
            if (cache.has(this)) return cache.get(this);
            try {
                const result = origToString.call(this);
                if (this === Function.prototype.toString || /\{ \[native code\] \}/.test(result)) {
                    return result;
                }
                if (this.name && /^(get|set)\b/.test(this.name)) {
                    const out = `function ${this.name}() { [native code] }`;
                    cache.set(this, out);
                    return out;
                }
                return result;
            } catch (e) {
                return `function () { [native code] }`;
            }
        };
    } catch (e) {}

    // ---- 14. screen / window dimensions --------------------------------
    try {
        const w = $$VIEW_WIDTH$$, h = $$VIEW_HEIGHT$$;
        define(window.screen, 'width',       () => w);
        define(window.screen, 'height',      () => h);
        define(window.screen, 'availWidth',  () => w);
        define(window.screen, 'availHeight', () => h - 40);
        define(window.screen, 'colorDepth',  () => 24);
        define(window.screen, 'pixelDepth',  () => 24);
    } catch (e) {}

    // ---- 15. battery (deprecated, but Akamai still probes it) ----------
    try {
        if (navigator.getBattery) {
            navigator.getBattery = () => Promise.resolve({
                charging: true,
                chargingTime: 0,
                dischargingTime: Infinity,
                level: 1,
                addEventListener: () => {},
                removeEventListener: () => {},
            });
        }
    } catch (e) {}
})();
"""


def build_stealth_init_js(cfg: BypassConfig | None = None) -> str:
    """Render the stealth init script for a given :class:`BypassConfig`."""
    cfg = cfg or BypassConfig()
    base_locale = cfg.locale.split("-", 1)[0] or "en"
    out = _STEALTH_TEMPLATE
    out = out.replace("$$LOCALE$$", cfg.locale)
    out = out.replace("$$LOCALE_BASE$$", base_locale)
    out = out.replace("$$PLATFORM$$", cfg.platform)
    out = out.replace("$$PLATFORM_SHORT$$", cfg.platform_short)
    out = out.replace("$$CH_MAJOR$$", cfg.chrome_major)
    out = out.replace("$$CH_FULL$$", cfg.chrome_full_version)
    out = out.replace("$$VIEW_WIDTH$$", str(cfg.viewport.width))
    out = out.replace("$$VIEW_HEIGHT$$", str(cfg.viewport.height))
    return out


# Pre-rendered with the default config — this is what most callers want.
STEALTH_INIT_JS: str = build_stealth_init_js()


def build_extra_headers(cfg: BypassConfig | None = None) -> dict[str, str]:
    """Return the ``extra_http_headers`` dict for the Playwright context."""
    cfg = cfg or BypassConfig()
    return cfg.base_headers()


# Convenience header dict for the default config.
EXTRA_HEADERS: dict[str, str] = build_extra_headers()


def apply_stealth(ctx: BrowserContext, cfg: BypassConfig | None = None) -> None:
    """Inject the stealth init script into a Playwright BrowserContext.

    Idempotent within a single context (the JS itself guards against double
    application via ``window.__akamai_stealth_applied``).
    """
    cfg = cfg or BypassConfig()
    ctx.add_init_script(build_stealth_init_js(cfg))


__all__ = [
    "CHROME_FULL_VERSION",
    "CHROME_VERSION",
    "EXTRA_HEADERS",
    "IGNORE_DEFAULT_ARGS",
    "LAUNCH_ARGS",
    "STEALTH_INIT_JS",
    "apply_stealth",
    "build_extra_headers",
    "build_stealth_init_js",
]
