import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

class FakeClassList {
    constructor(...names) {
        this.names = new Set(names);
    }
    add(...names) {
        names.forEach(name => this.names.add(name));
    }
    remove(...names) {
        names.forEach(name => this.names.delete(name));
    }
    contains(name) {
        return this.names.has(name);
    }
    toggle(name, force) {
        const enabled = force === undefined ? !this.contains(name) : force;
        if (enabled) this.add(name);
        else this.remove(name);
        return enabled;
    }
}

const element = (...classes) => ({
    classList: new FakeClassList(...classes),
    checked: false,
    scrollHeight: 100,
    scrollTop: 0
});

const elements = {
    "nav-audit": element("nav-active"),
    "nav-chat": element(),
    "nav-report": element(),
    "module-audit": element("module-content"),
    "module-chat": element("module-content", "hidden"),
    "module-report": element("module-content", "hidden"),
    "showAuditNavToggle": element(),
    "showReportNavToggle": element(),
    "appSidebar": element(),
    "sidebarExpandBtn": element("hidden"),
    "chatHistory": element()
};
const storage = new Map();
let readyHandler;

const document = {
    getElementById: id => elements[id] || null,
    querySelectorAll: selector => {
        if (selector === ".module-content") {
            return [elements["module-audit"], elements["module-chat"], elements["module-report"]];
        }
        if (selector === "nav button") {
            return [elements["nav-audit"], elements["nav-chat"], elements["nav-report"]];
        }
        return [];
    },
    addEventListener: (event, handler) => {
        if (event === "DOMContentLoaded") readyHandler = handler;
    }
};

const context = vm.createContext({
    console,
    document,
    localStorage: {
        getItem: key => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, String(value))
    }
});

vm.runInContext(fs.readFileSync("web/js/app.js", "utf8"), context);
readyHandler();

assert.equal(elements["showAuditNavToggle"].checked, false);
assert.equal(elements["showReportNavToggle"].checked, false);
assert.equal(elements["nav-audit"].classList.contains("hidden"), true);
assert.equal(elements["nav-report"].classList.contains("hidden"), true);

vm.runInContext("setFeatureNavigation('audit', true); switchModule('audit')", context);
vm.runInContext("setFeatureNavigation('audit', false)", context);
assert.equal(elements["nav-audit"].classList.contains("hidden"), true);
assert.equal(elements["module-chat"].classList.contains("hidden"), false);
assert.equal(JSON.parse(storage.get("customs_navigation_preferences_v2")).audit, false);

vm.runInContext("setSidebarCollapsed(true)", context);
assert.equal(elements.appSidebar.classList.contains("hidden"), true);
assert.equal(elements.sidebarExpandBtn.classList.contains("hidden"), false);

vm.runInContext("setSidebarCollapsed(false)", context);
assert.equal(elements.appSidebar.classList.contains("hidden"), false);
assert.equal(elements.sidebarExpandBtn.classList.contains("hidden"), true);

console.log("web navigation preferences contract passed");
