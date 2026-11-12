import {mountProductHeader} from "./networkpunkt-product-header.js";
const slot = document.querySelector("[data-product-header]");
if (slot) mountProductHeader(slot, {
  selfId:"threaddesk", locale:document.documentElement.lang,
  // Native closure accepts only a catalog ID. Browser mode keeps the missing-target UI.
  ...(typeof window.__THREADDESK_FAMILY__?.switchTarget === "function"
    ? {openTarget:appId => window.__THREADDESK_FAMILY__.switchTarget(appId)} : {})
});
