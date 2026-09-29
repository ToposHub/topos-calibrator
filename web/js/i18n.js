/**
 * Topos Calibrator - 轻量国际化 (i18n) 模块
 *
 * 设计要点：
 * 1. 以「中文原文」作为翻译 key：迁移成本低，漏翻时自动回退显示中文原文，
 *    未来新增语言只需在 locales/ 下新增一个语言包文件并调用 I18N.register()。
 * 2. 语言包以 .js 文件提供（而非 JSON fetch），因为应用通过 file:// 协议加载，
 *    fetch 本地 JSON 会被浏览器安全策略拦截。
 * 3. 静态与动态插入 DOM 的中文文本由 DOM 遍历器 + MutationObserver 自动翻译
 *    （含 title/placeholder/aria-label/data-desc 属性），因此绝大多数 HTML 模板无需改造；
 *    仅原生对话框（alert/confirm）与「值+中文混排」的纯文本需要用 I18N.t() 包裹。
 * 4. 语言偏好持久化在 localStorage (key: topos.lang)。
 *
 * 用法：
 *   I18N.t('连接探头')                 // => 'Connect Probe'（英文模式下）
 *   I18N.t('已完成 {n} 个', {n: 3})    // => '3 completed'
 *   I18N.setLanguage('en')             // 切换语言并刷新整个 DOM
 *   I18N.getLanguage()                 // => 'en'
 *   I18N.onChange(fn)                  // 监听语言变化（用于动态区域重渲染）
 */
(function (global) {
    'use strict';

    var STORAGE_KEY = 'topos.lang';
    // Chinese systems use Chinese; unknown/non-Chinese systems fall back to English.
    var DEFAULT_LANG = 'en';

    // 已注册的语言包：{ 'en': { '中文': 'English', ... }, ... }
    var locales = {};
    // 当前语言与当前字典（zh-CN 不注册字典，t() 直接返回原文）
    var currentLang = DEFAULT_LANG;
    var currentDict = null;

    // 支持的语言列表（菜单展示用）。新增语言时在此登记即可出现在切换菜单中。
    var supportedLanguages = [
        { code: 'zh-CN', name: '简体中文' },
        { code: 'en', name: 'English' }
    ];

    // 语言变化监听器
    var changeListeners = [];

    // 原始 <title>（首次 walk 时记录）
    var originalTitle = null;

    // ---------- 工具函数 ----------

    function detectLanguage() {
        try {
            var saved = global.localStorage && global.localStorage.getItem(STORAGE_KEY);
            if (saved && isLanguageAvailable(saved)) return saved;
        } catch (e) { /* localStorage 不可用时忽略 */ }

        // 依据浏览器语言自动选择（仅在接受的语言中匹配，否则回退默认）
        var nav = (global.navigator && global.navigator.language) || '';
        nav = nav.toLowerCase();
        for (var i = 0; i < supportedLanguages.length; i++) {
            var code = supportedLanguages[i].code.toLowerCase();
            if (nav === code || nav.indexOf(code + '-') === 0) return supportedLanguages[i].code;
        }
        // navigator.language 形如 zh / en-US 的前缀匹配
        var prefix = nav.split('-')[0];
        if (prefix === 'zh') return 'zh-CN';
        if (prefix === 'en') return 'en';
        return DEFAULT_LANG;
    }

    function isLanguageAvailable(lang) {
        for (var i = 0; i < supportedLanguages.length; i++) {
            if (supportedLanguages[i].code === lang) return true;
        }
        return false;
    }

    function persistLanguage(lang) {
        try {
            global.localStorage.setItem(STORAGE_KEY, lang);
        } catch (e) { /* 忽略 */ }
    }

    /**
     * 对 {name} 形式的占位符做插值。
     * t('共 {total} 条', {total: 5}) => '共 5 条'
     */
    function interpolate(template, params) {
        if (!params) return template;
        return template.replace(/\{(\w+)\}/g, function (m, key) {
            return Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : m;
        });
    }

    // ---------- 核心翻译 API ----------

    /**
     * 翻译一个字符串。key 即中文原文；找不到翻译时原样返回（优雅回退）。
     * @param {string} text 中文原文（可含 {placeholder}）
     * @param {Object} [params] 占位符取值
     */
    function t(text, params) {
        if (typeof text !== 'string') return text;
        if (currentDict) {
            var hit = currentDict[text];
            if (typeof hit === 'string') return interpolate(hit, params);
        }
        return interpolate(text, params);
    }

    // ---------- DOM 翻译 ----------

    // 需要翻译的属性列表
    var TRANSLATABLE_ATTRS = ['title', 'placeholder', 'aria-label', 'data-desc', 'data-tooltip'];

    // 不进入的元素（脚本/样式/组件内部）
    var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1 };

    /**
     * 记录节点原始文本（首次处理时），便于切换回中文时还原。
     */
    function rememberOriginal(node) {
        if (node.__i18nOriginal === undefined) {
            node.__i18nOriginal = node.nodeValue;
        }
    }

    function translateTextNode(node) {
        var target = targetForTextNode(node);
        // 幂等写入：目标值与当前值相同则不动 DOM（避免触发观察者造成循环）
        if (target !== null && node.nodeValue !== target) {
            node.nodeValue = target;
        }
    }

    /**
     * 计算文本节点的目标显示值。以首次记录的原文为基准：
     * - 非源语言且有翻译：原文的排版空白 + 译文
     * - 无翻译或源语言：还原原文
     * 该计算是幂等的，重复调用不会产生新的 DOM 变更。
     */
    function targetForTextNode(node) {
        var raw = node.nodeValue;
        if (!raw) return null;
        rememberOriginal(node);
        var original = node.__i18nOriginal;
        var trimmed = original.trim();
        if (!trimmed) return null;
        var translated = t(trimmed);
        if (currentDict && translated !== trimmed) {
            var idx = original.indexOf(trimmed);
            return original.slice(0, idx) + translated + original.slice(idx + trimmed.length);
        }
        return original;
    }

    function translateElement(el) {
        // 属性翻译（幂等：始终依据记录的原始值计算目标值）
        for (var i = 0; i < TRANSLATABLE_ATTRS.length; i++) {
            var name = TRANSLATABLE_ATTRS[i];
            if (!el.hasAttribute(name)) continue;
            var val = el.getAttribute(name);
            if (!val) continue;
            if (el.__i18nAttrOriginal === undefined) {
                el.__i18nAttrOriginal = {};
            }
            if (el.__i18nAttrOriginal[name] === undefined) {
                el.__i18nAttrOriginal[name] = val;
            }
            var original = el.__i18nAttrOriginal[name];
            if (!original.trim()) continue;
            var translated = t(original.trim());
            var target = (currentDict && translated !== original.trim())
                ? translated
                : original;
            if (val !== target) {
                el.setAttribute(name, target);
            }
        }
    }

    /**
     * 遍历 document 并翻译所有文本节点与可翻译属性。
     * 初次挂载与每次语言切换后调用。TreeWalker 不修改结构，性能可接受。
     */
    function walkDocument(root) {
        root = root || global.document.body;
        if (!root) return;

        var walker = global.document.createTreeWalker(root, global.NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                if (!node.parentNode) return global.NodeFilter.FILTER_REJECT;
                if (SKIP_TAGS[node.parentNode.tagName]) return global.NodeFilter.FILTER_REJECT;
                return global.NodeFilter.FILTER_ACCEPT;
            }
        });
        // 先收集再修改，避免遍历过程中受 DOM 变化影响
        var nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        for (var i = 0; i < nodes.length; i++) translateTextNode(nodes[i]);

        var all = root.querySelectorAll ? root.querySelectorAll('*') : [];
        for (var j = 0; j < all.length; j++) translateElement(all[j]);

        // <title> 在 <head> 中，单独处理（记录原始标题，始终从原文翻译）
        if (root === global.document.body && global.document) {
            if (originalTitle === null) originalTitle = global.document.title;
            global.document.title = t(originalTitle);
        }
    }

    // ---------- 动态 DOM 监听 ----------

    var observer = null;
    var pendingNodes = null;       // 收集待处理节点，微任务中批量翻译

    function queueProcess(mutations) {
        if (!pendingNodes) {
            pendingNodes = new Set();
            Promise.resolve().then(flushPending);
        }
        for (var i = 0; i < mutations.length; i++) {
            var m = mutations[i];
            if (m.type === 'characterData' && m.target) {
                pendingNodes.add(m.target);
            } else if (m.type === 'childList') {
                for (var j = 0; j < m.addedNodes.length; j++) {
                    var n = m.addedNodes[j];
                    if (n.nodeType === 3) pendingNodes.add(n);
                    else if (n.nodeType === 1) pendingNodes.add(n);
                }
            } else if (m.type === 'attributes') {
                // 属性变更只处理该元素的属性，避免整棵子树重翻带来的 O(n²) 开销
                var el = m.target;
                if (el && el.nodeType === 1) {
                    var id = elementId(el);
                    pendingNodes.add('a:' + id);
                    attrTargets.set(id, el);
                }
            }
        }
    }

    var nextI18nId = 1;
    var attrTargets = new Map(); // __i18nId -> element

    function elementId(el) {
        if (el.__i18nId === undefined) el.__i18nId = nextI18nId++;
        return el.__i18nId;
    }

    function flushPending() {
        var batch = pendingNodes;
        pendingNodes = null;
        if (!batch) return;
        // 翻译为幂等操作：已达到目标值的节点不再写 DOM，因此不会造成观察者循环
        batch.forEach(function (n) {
            if (typeof n === 'string' && n.charAt(0) === 'a') {
                var el = attrTargets.get(n.slice(2));
                if (el && el.isConnected) translateElement(el);
                return;
            }
            if (n.nodeType === 3) {
                // 文本节点：父元素不得是跳过标签
                if (n.parentNode && !SKIP_TAGS[n.parentNode.tagName]) translateTextNode(n);
            } else if (n.nodeType === 1) {
                // 元素节点：新增的 HTML 片段，翻译整个子树
                walkDocument(n);
            }
        });
        // 清理本轮的属性目标映射
        batch.forEach(function (n) {
            if (typeof n === 'string' && n.charAt(0) === 'a') attrTargets.delete(n.slice(2));
        });
    }

    function startObserver() {
        if (!global.MutationObserver || observer) return;
        observer = new global.MutationObserver(queueProcess);
        observer.observe(global.document.body, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
            attributeFilter: TRANSLATABLE_ATTRS
        });
    }

    // ---------- 公开 API ----------

    var I18N = {
        /**
         * 注册语言包。语言包文件（locales/*.js）加载后调用。
         * @param {string} lang 语言代码，如 'en'
         * @param {Object<string,string>} dict { 中文原文: 译文 }
         */
        register: function (lang, dict) {
            locales[lang] = dict || {};
            if (lang === currentLang) currentDict = locales[lang];
        },

        /** 当前语言代码 */
        getLanguage: function () {
            return currentLang;
        },

        /** 支持的语言列表（[{code, name}]），供语言菜单渲染 */
        getSupportedLanguages: function () {
            return supportedLanguages.slice();
        },

        /** 是否存在指定语言的翻译包 */
        isLanguageAvailable: isLanguageAvailable,

        /**
         * 切换语言：持久化、更新字典、重译 DOM、广播变化。
         * @param {string} lang 语言代码
         * @returns {boolean} 是否切换成功
         */
        setLanguage: function (lang) {
            if (!isLanguageAvailable(lang)) return false;
            currentLang = lang;
            currentDict = locales[lang] || null;
            persistLanguage(lang);
            if (global.document && global.document.documentElement) {
                global.document.documentElement.setAttribute('lang', lang);
            }
            walkDocument();
            for (var i = 0; i < changeListeners.length; i++) {
                try { changeListeners[i](lang); } catch (e) { /* 监听器异常不阻断 */ }
            }
            return true;
        },

        /** 订阅语言变化。fn(lang) */
        onChange: function (fn) {
            if (typeof fn === 'function') changeListeners.push(fn);
        },

        /** 翻译函数（同模块级 t） */
        t: t,

        /** 手动触发一次 DOM 翻译（动态插入整块静态 HTML 后可用） */
        refresh: function () {
            walkDocument();
        }
    };

    // ---------- 启动 ----------

    function init() {
        currentLang = detectLanguage();
        currentDict = locales[currentLang] || null;
        if (global.document && global.document.documentElement) {
            global.document.documentElement.setAttribute('lang', currentLang);
        }
        if (global.document && global.document.readyState === 'loading') {
            global.document.addEventListener('DOMContentLoaded', function () {
                walkDocument();
                startObserver();
                for (var i = 0; i < changeListeners.length; i++) {
                    try { changeListeners[i](currentLang); } catch (e) { /* 忽略 */ }
                }
            });
        } else if (global.document) {
            walkDocument();
            startObserver();
        }
    }

    init();

    // 全局暴露 t()，保证后加载的脚本（charts.js 等）在顶层执行时也可用
    global.t = t;

    global.I18N = I18N;
})(window);
