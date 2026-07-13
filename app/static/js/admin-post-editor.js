(function () {
    'use strict';

    const app = document.getElementById('post-editor-app');
    const configElement = document.getElementById('post-editor-config');
    if (!app || !configElement) return;

    let config;
    try {
        config = JSON.parse(configElement.textContent || '{}');
    } catch (error) {
        console.error('文章编辑器配置解析失败：', error);
        return;
    }

    function createDraftId() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return window.crypto.randomUUID();
        }
        const bytes = new Uint8Array(16);
        if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
            window.crypto.getRandomValues(bytes);
        } else {
            for (let index = 0; index < bytes.length; index += 1) {
                bytes[index] = Math.floor(Math.random() * 256);
            }
        }
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }

    function ensureNewDraftId() {
        const postId = Number.isInteger(config.post_id) ? config.post_id : null;
        if (postId || !Boolean(config.is_new)) return null;

        const url = new URL(window.location.href);
        const requestedId = url.searchParams.get('draft') || '';
        const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
        const draftId = uuidPattern.test(requestedId) ? requestedId.toLowerCase() : createDraftId();
        if (requestedId !== draftId) {
            url.searchParams.set('draft', draftId);
            window.history.replaceState(
                window.history.state,
                '',
                `${url.pathname}${url.search}${url.hash}`
            );
        }
        return draftId;
    }

    const newDraftId = ensureNewDraftId();

    const elements = {
        form: document.getElementById('post-editor-form'),
        title: document.getElementById('post-title'),
        content: document.getElementById('post-content'),
        slug: document.getElementById('post-slug'),
        summary: document.getElementById('post-summary'),
        category: document.getElementById('post-category'),
        tags: document.getElementById('post-tags'),
        preview: document.getElementById('post-preview'),
        workspace: document.getElementById('post-editor-workspace'),
        saveStatus: document.getElementById('editor-save-status'),
        localStatus: document.getElementById('editor-local-status'),
        wordCount: document.getElementById('editor-word-count'),
        formError: document.getElementById('editor-form-error'),
        documentLabel: document.getElementById('editor-document-label'),
        publicationStatus: document.getElementById('editor-publication-status'),
        publicationHint: document.getElementById('editor-publication-hint'),
        viewLink: document.getElementById('editor-view-link'),
        settingsToggle: document.getElementById('editor-settings-toggle'),
        settingsClose: document.getElementById('editor-settings-close'),
        settingsBackdrop: document.getElementById('editor-settings-backdrop'),
        settingsDrawer: document.getElementById('editor-settings-drawer'),
        imageInput: document.getElementById('editor-image-input'),
        uploadStatus: document.getElementById('editor-upload-status'),
        restoreBanner: document.getElementById('editor-restore-banner'),
        restoreMessage: document.getElementById('editor-restore-message'),
        restoreDraft: document.getElementById('editor-restore-draft'),
        discardDraft: document.getElementById('editor-discard-draft'),
        generateSummary: document.getElementById('editor-generate-summary')
    };

    if (Object.values(elements).some(element => !element)) {
        console.error('文章编辑器缺少必要的 DOM 节点。');
        return;
    }

    const state = {
        postId: Number.isInteger(config.post_id) ? config.post_id : null,
        newDraftId,
        isNew: Boolean(config.is_new),
        isPublished: false,
        isLoading: true,
        isSaving: false,
        isDirty: false,
        hasConflict: false,
        pendingUploads: 0,
        uploadFailureCount: 0,
        uploadWaveTotal: 0,
        etag: null,
        slugManuallyEdited: false,
        lastServerSnapshot: '',
        lastSavedSlug: '',
        serverUpdatedAt: 0,
        pendingRestore: null,
        localSaveTimer: null,
        previewTimer: null,
        titleResizeFrame: null,
        previewHighlightFrame: null,
        scrollSyncFrame: null,
        settingsReturnFocus: null
    };

    const LOCAL_DRAFT_PREFIX = 'post-editor:draft:';
    const MODE_STORAGE_KEY = 'post-editor:view-mode';
    const PREVIEW_DELAY_MS = 200;
    const LOCAL_SAVE_DELAY_MS = 1000;
    const IMAGE_UPLOAD_TIMEOUT_MS = 60_000;

    function getDraftKey(postId = state.postId) {
        return `${LOCAL_DRAFT_PREFIX}${postId ? `post:${postId}` : `new:${state.newDraftId}`}`;
    }

    function safeStorageGet(key) {
        try {
            return window.localStorage.getItem(key);
        } catch (error) {
            return null;
        }
    }

    function safeStorageRemove(key) {
        try {
            window.localStorage.removeItem(key);
        } catch (error) {
            // 隐私模式或浏览器策略可能禁止访问 localStorage，无需中断写作。
        }
    }

    function setSaveStatus(message, status = 'idle') {
        elements.saveStatus.dataset.state = status;
        const label = elements.saveStatus.querySelector('strong');
        if (label) label.textContent = message;
    }

    function setUploadStatus(message, status = 'idle') {
        elements.uploadStatus.dataset.state = status;
        elements.uploadStatus.textContent = message;
    }

    function setFormError(message) {
        const normalized = String(message || '').trim();
        elements.formError.textContent = normalized;
        elements.formError.hidden = !normalized;
        if (normalized) elements.formError.focus({ preventScroll: true });
    }

    function setFieldError(field, message) {
        const errorElement = document.querySelector(`[data-error-for="${field}"]`);
        const input = elements[field];
        if (!errorElement || !input) return;
        errorElement.textContent = String(message || '');
        errorElement.hidden = !message;
        input.setAttribute('aria-invalid', message ? 'true' : 'false');
    }

    function clearErrors() {
        setFormError('');
        ['title', 'content', 'slug', 'summary', 'category', 'tags'].forEach(field => {
            setFieldError(field, '');
        });
    }

    function captureFields() {
        return {
            title: elements.title.value,
            slug: elements.slug.value,
            summary: elements.summary.value,
            category: elements.category.value,
            tags: elements.tags.value,
            content: elements.content.value
        };
    }

    function stripUploadPlaceholders(content) {
        return String(content || '')
            .replace(/!\[[^\]]*\]\(Uploading-[^)]+\)\n?/g, '');
    }

    function captureLocalDraftFields() {
        const fields = captureFields();
        fields.content = stripUploadPlaceholders(fields.content);
        return fields;
    }

    function serializeFields(fields = captureFields()) {
        return JSON.stringify(fields);
    }

    function updateDirtyState() {
        if (state.isLoading) return;
        state.isDirty = state.hasConflict || serializeFields() !== state.lastServerSnapshot;
        if (state.isSaving) return;
        if (state.isDirty) {
            setSaveStatus('有未保存修改', 'dirty');
        } else {
            window.clearTimeout(state.localSaveTimer);
            if (!state.pendingRestore) safeStorageRemove(getDraftKey());
            elements.localStatus.textContent = '当前内容已与服务器一致';
            setSaveStatus('已与服务器同步', 'saved');
        }
    }

    function setControlsBusy() {
        const shouldDisableSave = state.isLoading || state.isSaving || state.pendingUploads > 0;
        document.querySelectorAll('.post-editor-save-draft, .post-editor-publish').forEach(button => {
            button.disabled = shouldDisableSave;
            button.setAttribute('aria-busy', state.isSaving ? 'true' : 'false');
        });
    }

    function updatePublicationUI() {
        elements.publicationStatus.dataset.published = String(state.isPublished);
        elements.publicationStatus.replaceChildren();

        const icon = document.createElement('i');
        icon.className = state.isPublished
            ? 'fa-solid fa-circle-check'
            : 'fa-solid fa-circle-pause';
        icon.setAttribute('aria-hidden', 'true');
        elements.publicationStatus.append(icon, document.createTextNode(
            state.isPublished ? ' 已发布' : ' 草稿'
        ));

        document.querySelectorAll('.post-editor-publish span').forEach(label => {
            label.textContent = state.isPublished ? '更新并发布' : '发布文章';
        });
        document.querySelectorAll('.post-editor-save-draft span').forEach(label => {
            label.textContent = state.isPublished ? '撤回为草稿' : '保存草稿';
        });
        document.querySelectorAll('.post-editor-save-draft').forEach(button => {
            button.title = state.isPublished
                ? '保存当前修改并将线上文章撤回为草稿'
                : '将当前内容保存为未公开草稿';
            button.setAttribute(
                'aria-label',
                state.isPublished ? '撤回文章并保存为草稿' : '保存草稿'
            );
        });
        elements.publicationHint.textContent = state.isPublished
            ? '“撤回为草稿”会立即停止公开这篇文章；“更新并发布”会直接更新线上内容。'
            : '“保存草稿”不会公开文章；“发布文章”会立即更新线上内容。';
        elements.documentLabel.textContent = state.postId
            ? `EDIT / ${state.isPublished ? 'PUBLISHED' : 'DRAFT'}`
            : 'NEW / DRAFT';
        elements.saveStatus.title = state.isPublished
            ? '已发布文章中按 Cmd/Ctrl+S 会直接更新线上内容'
            : '按 Cmd/Ctrl+S 保存为草稿';
    }

    function updateViewLink() {
        if (!state.postId || !state.lastSavedSlug) {
            elements.viewLink.hidden = true;
            elements.viewLink.removeAttribute('href');
            return;
        }
        elements.viewLink.href = `/blog/${encodeURIComponent(state.lastSavedSlug)}`;
        elements.viewLink.hidden = false;
    }

    function generateSlug(title) {
        return String(title || '')
            .normalize('NFKC')
            .toLocaleLowerCase('zh-CN')
            .replace(/[^\p{L}\p{N}_\s-]/gu, '')
            .trim()
            .replace(/\s+/g, '-')
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '');
    }

    function autoResizeTitle() {
        window.cancelAnimationFrame(state.titleResizeFrame);
        state.titleResizeFrame = window.requestAnimationFrame(() => {
            elements.title.style.height = 'auto';
            elements.title.style.height = `${Math.max(elements.title.scrollHeight, 54)}px`;
        });
    }

    function updateStats() {
        const content = elements.content.value.trim();
        const characterCount = content ? Array.from(content.replace(/\s/g, '')).length : 0;
        const readingMinutes = characterCount ? Math.max(1, Math.ceil(characterCount / 500)) : 0;
        elements.wordCount.textContent = `${characterCount.toLocaleString('zh-CN')} 字 · 约 ${readingMinutes} 分钟阅读`;
    }

    function preprocessMarkdown(text) {
        if (!text) return '';
        const lines = text.split(/\r?\n/);
        const output = [];
        const listItemPattern = /^\s*([-*+]|\d+\.)\s+/;

        lines.forEach((line, index) => {
            let processed = line;
            const indentMatch = line.match(/^(\s*)([-*+]|\d+\.)(\s+)(.*)/);
            if (indentMatch && indentMatch[1].length > 0) {
                const indent = Math.max(4, Math.floor((indentMatch[1].length + 2) / 4) * 4);
                processed = `${' '.repeat(indent)}${indentMatch[2]}${indentMatch[3]}${indentMatch[4]}`;
            }

            if (index > 0 && listItemPattern.test(processed)) {
                const previous = lines[index - 1].trim();
                if (
                    previous &&
                    !listItemPattern.test(previous) &&
                    !previous.startsWith('#') &&
                    !previous.startsWith('>') &&
                    !previous.startsWith('`')
                ) {
                    output.push('');
                }
            }
            output.push(processed);
        });
        return output.join('\n');
    }

    function escapeRawHtml(markdown) {
        return String(markdown || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function isSafeUrl(rawUrl, options = {}) {
        const value = String(rawUrl || '').trim();
        if (!value) return false;
        if (value.startsWith('#') || value.startsWith('/') || value.startsWith('./') || value.startsWith('../')) {
            return true;
        }
        if (options.allowImageData && /^data:image\/(?:png|jpe?g|gif|webp);base64,/i.test(value)) {
            return true;
        }
        try {
            const parsed = new URL(value, window.location.origin);
            const protocols = options.image
                ? ['http:', 'https:']
                : ['http:', 'https:', 'mailto:', 'tel:'];
            return protocols.includes(parsed.protocol);
        } catch (error) {
            return false;
        }
    }

    function sanitizePreview(markdown) {
        const fragmentTemplate = document.createElement('template');
        const safeInput = escapeRawHtml(preprocessMarkdown(markdown));
        fragmentTemplate.innerHTML = window.marked.parse(safeInput, {
            gfm: true,
            breaks: true,
            mangle: false,
            headerIds: false
        });

        const allowedTags = new Set([
            'A', 'BLOCKQUOTE', 'BR', 'CODE', 'DEL', 'EM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
            'HR', 'IMG', 'INPUT', 'LI', 'OL', 'P', 'PRE', 'STRONG', 'TABLE', 'TBODY', 'TD', 'TH',
            'THEAD', 'TR', 'UL'
        ]);

        fragmentTemplate.content.querySelectorAll('*').forEach(element => {
            if (!allowedTags.has(element.tagName)) {
                element.replaceWith(document.createTextNode(element.textContent || ''));
                return;
            }

            const retainedAttributes = new Set();
            if (element.tagName === 'A') {
                retainedAttributes.add('href');
                retainedAttributes.add('title');
            }
            if (element.tagName === 'IMG') {
                retainedAttributes.add('src');
                retainedAttributes.add('alt');
                retainedAttributes.add('title');
            }
            if (element.tagName === 'INPUT') {
                retainedAttributes.add('type');
                retainedAttributes.add('checked');
                retainedAttributes.add('disabled');
            }
            if (element.tagName === 'OL') retainedAttributes.add('start');
            if (element.tagName === 'TD' || element.tagName === 'TH') retainedAttributes.add('align');

            Array.from(element.attributes).forEach(attribute => {
                const name = attribute.name.toLowerCase();
                const classIsSafe = name === 'class' && (
                    /^(?:language-[\w-]+|task-list-item|contains-task-list)$/.test(attribute.value)
                );
                if (!retainedAttributes.has(name) && !classIsSafe) {
                    element.removeAttribute(attribute.name);
                }
            });

            if (element.tagName === 'A') {
                const href = element.getAttribute('href');
                if (!isSafeUrl(href)) {
                    element.removeAttribute('href');
                    element.title = '已阻止不安全链接';
                } else {
                    element.setAttribute('href', href);
                    try {
                        const parsed = new URL(href, window.location.origin);
                        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                            element.target = '_blank';
                            element.rel = 'noopener noreferrer';
                        }
                    } catch (error) {
                        // 相对地址不需要额外处理。
                    }
                }
            }

            if (element.tagName === 'IMG') {
                const src = element.getAttribute('src');
                if (!isSafeUrl(src, { image: true, allowImageData: true })) {
                    element.removeAttribute('src');
                    element.alt = '已阻止不安全图片地址';
                } else {
                    element.setAttribute('src', src);
                    element.loading = 'lazy';
                    element.decoding = 'async';
                }
            }

            if (element.tagName === 'INPUT') {
                const isCheckbox = element.getAttribute('type') === 'checkbox';
                const checked = element.hasAttribute('checked');
                Array.from(element.attributes).forEach(attribute => element.removeAttribute(attribute.name));
                if (!isCheckbox) {
                    element.remove();
                    return;
                }
                element.type = 'checkbox';
                element.disabled = true;
                element.checked = checked;
            }
        });
        return fragmentTemplate.content;
    }

    function renderPreview() {
        window.clearTimeout(state.previewTimer);
        const markdown = elements.content.value;
        if (!markdown.trim()) {
            const empty = document.createElement('p');
            empty.className = 'post-editor-preview-empty';
            empty.textContent = '正文预览会显示在这里。';
            elements.preview.replaceChildren(empty);
            return;
        }
        if (!window.marked || typeof window.marked.parse !== 'function') {
            const error = document.createElement('p');
            error.className = 'post-editor-preview-empty';
            error.textContent = 'Markdown 预览组件加载失败，正文仍可正常保存。';
            elements.preview.replaceChildren(error);
            return;
        }

        try {
            elements.preview.replaceChildren(sanitizePreview(markdown));
            window.cancelAnimationFrame(state.previewHighlightFrame);
            state.previewHighlightFrame = window.requestAnimationFrame(() => {
                if (window.Prism && typeof window.Prism.highlightAllUnder === 'function') {
                    window.Prism.highlightAllUnder(elements.preview);
                }
            });
        } catch (error) {
            console.error('Markdown 预览失败：', error);
            const message = document.createElement('p');
            message.className = 'post-editor-preview-empty';
            message.textContent = '预览暂时不可用，正文内容不会受到影响。';
            elements.preview.replaceChildren(message);
        }
    }

    function schedulePreview() {
        window.clearTimeout(state.previewTimer);
        state.previewTimer = window.setTimeout(renderPreview, PREVIEW_DELAY_MS);
    }

    function saveDraftLocally(options = {}) {
        window.clearTimeout(state.localSaveTimer);
        if (state.pendingRestore && !options.force) return;
        if (!state.isDirty && !options.force) return;

        const record = {
            version: 1,
            postId: state.postId,
            draftId: state.newDraftId,
            savedAt: Date.now(),
            isPublished: state.isPublished,
            hasConflict: state.hasConflict,
            fields: captureLocalDraftFields()
        };
        try {
            window.localStorage.setItem(getDraftKey(), JSON.stringify(record));
            const time = new Intl.DateTimeFormat('zh-CN', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            }).format(new Date(record.savedAt));
            elements.localStatus.textContent = `本地草稿已保存于 ${time}`;
            if (!state.isSaving) setSaveStatus('修改已在本机暂存', 'dirty');
        } catch (error) {
            elements.localStatus.textContent = '本地草稿保存失败，请尽快保存到服务器';
            if (!state.isSaving) setSaveStatus('无法写入本地草稿', 'error');
        }
    }

    function scheduleLocalSave() {
        window.clearTimeout(state.localSaveTimer);
        if (state.pendingRestore) return;
        state.localSaveTimer = window.setTimeout(saveDraftLocally, LOCAL_SAVE_DELAY_MS);
    }

    function readLocalDraft() {
        const raw = safeStorageGet(getDraftKey());
        if (!raw) return null;
        try {
            const draft = JSON.parse(raw);
            if (!draft || draft.version !== 1 || !draft.fields || typeof draft.savedAt !== 'number') {
                safeStorageRemove(getDraftKey());
                return null;
            }
            if ((draft.postId || null) !== (state.postId || null)) return null;
            if (!state.postId && draft.draftId && draft.draftId !== state.newDraftId) return null;
            draft.fields.content = stripUploadPlaceholders(draft.fields.content);
            return draft;
        } catch (error) {
            safeStorageRemove(getDraftKey());
            return null;
        }
    }

    function offerLocalDraftIfNeeded() {
        const draft = readLocalDraft();
        if (!draft) return;
        const differsFromServer = serializeFields(draft.fields) !== state.lastServerSnapshot;
        if (!differsFromServer) {
            safeStorageRemove(getDraftKey());
            return;
        }
        state.pendingRestore = draft;
        elements.restoreMessage.textContent = draft.savedAt > state.serverUpdatedAt
            ? '检测到尚未同步到服务器的本地草稿。'
            : '检测到与服务器内容不同的本地草稿（它可能较旧），请自行选择恢复或忽略。';
        elements.restoreBanner.hidden = false;
    }

    function applyFields(fields) {
        elements.title.value = String(fields.title || '');
        elements.slug.value = String(fields.slug || '');
        elements.summary.value = String(fields.summary || '');
        elements.category.value = String(fields.category || 'Tech');
        elements.tags.value = String(fields.tags || '');
        elements.content.value = stripUploadPlaceholders(fields.content);
        autoResizeTitle();
        updateStats();
        renderPreview();
        updateViewLink();
    }

    function restoreLocalDraft() {
        const draft = state.pendingRestore;
        if (!draft) return;
        applyFields(draft.fields);
        state.slugManuallyEdited = Boolean(elements.slug.value);
        state.isPublished = Boolean(draft.isPublished);
        state.hasConflict = Boolean(draft.hasConflict);
        state.pendingRestore = null;
        elements.restoreBanner.hidden = true;
        updatePublicationUI();
        updateDirtyState();
        setSaveStatus('已恢复本地草稿', 'dirty');
        elements.localStatus.textContent = '本地草稿已恢复，尚未同步到服务器';
        if (state.hasConflict) {
            setFormError('该草稿来自一次版本冲突。当前页面已加载服务器最新版，确认内容后可再次保存。');
        }
        elements.title.focus();
    }

    function discardLocalDraft() {
        safeStorageRemove(getDraftKey());
        state.pendingRestore = null;
        elements.restoreBanner.hidden = true;
        elements.localStatus.textContent = '已忽略旧的本地草稿';
        updateDirtyState();
        scheduleLocalSave();
    }

    function handleEditorInput(event) {
        if (event.target === elements.slug && event.isTrusted) {
            state.slugManuallyEdited = true;
        }
        if (event.target === elements.title && !state.slugManuallyEdited) {
            elements.slug.value = generateSlug(elements.title.value);
        }
        if (event.target === elements.title) autoResizeTitle();
        if (event.target === elements.content) {
            schedulePreview();
            updateStats();
        }
        const fieldName = event.target.name;
        if (fieldName) setFieldError(fieldName, '');
        updateDirtyState();
        scheduleLocalSave();
    }

    function dispatchEditorInput(element) {
        element.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function replaceSelection(prefix, suffix, placeholder, options = {}) {
        const textarea = elements.content;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const selected = textarea.value.slice(start, end) || placeholder;
        const insertion = `${prefix}${selected}${suffix}`;
        textarea.setRangeText(insertion, start, end, 'end');
        const selectionStart = start + prefix.length;
        textarea.setSelectionRange(selectionStart, selectionStart + selected.length);
        if (options.selectSuffix) {
            const suffixStart = start + prefix.length + selected.length + options.selectSuffix.offset;
            textarea.setSelectionRange(suffixStart, suffixStart + options.selectSuffix.length);
        }
        textarea.focus();
        dispatchEditorInput(textarea);
    }

    function prefixSelectedLines(prefixFactory) {
        const textarea = elements.content;
        const value = textarea.value;
        const selectionStart = textarea.selectionStart;
        const selectionEnd = textarea.selectionEnd;
        const lineStart = value.lastIndexOf('\n', Math.max(0, selectionStart - 1)) + 1;
        const nextBreak = value.indexOf('\n', selectionEnd);
        const lineEnd = nextBreak === -1 ? value.length : nextBreak;
        const lines = value.slice(lineStart, lineEnd).split('\n');
        const replacement = lines.map((line, index) => `${prefixFactory(index)}${line}`).join('\n');
        textarea.setRangeText(replacement, lineStart, lineEnd, 'select');
        textarea.focus();
        dispatchEditorInput(textarea);
    }

    function insertMarkdown(action) {
        switch (action) {
            case 'heading-2':
                prefixSelectedLines(() => '## ');
                break;
            case 'heading-3':
                prefixSelectedLines(() => '### ');
                break;
            case 'heading-4':
                prefixSelectedLines(() => '#### ');
                break;
            case 'bold':
                replaceSelection('**', '**', '加粗文字');
                break;
            case 'italic':
                replaceSelection('*', '*', '斜体文字');
                break;
            case 'link': {
                const textarea = elements.content;
                const start = textarea.selectionStart;
                const end = textarea.selectionEnd;
                const label = textarea.value.slice(start, end) || '链接文字';
                const insertion = `[${label}](https://)`;
                textarea.setRangeText(insertion, start, end, 'end');
                const urlStart = start + label.length + 3;
                textarea.setSelectionRange(urlStart, urlStart + 8);
                textarea.focus();
                dispatchEditorInput(textarea);
                break;
            }
            case 'quote':
                prefixSelectedLines(() => '> ');
                break;
            case 'unordered-list':
                prefixSelectedLines(() => '- ');
                break;
            case 'ordered-list':
                prefixSelectedLines(index => `${index + 1}. `);
                break;
            case 'inline-code':
                replaceSelection('`', '`', '代码');
                break;
            case 'code-block':
                replaceSelection('\n```\n', '\n```\n', '在这里输入代码');
                break;
            case 'separator':
                replaceSelection('\n\n---\n\n', '', '');
                break;
            case 'image':
                elements.imageInput.click();
                break;
            default:
                break;
        }
    }

    function indentSelection(event) {
        event.preventDefault();
        const textarea = elements.content;
        const value = textarea.value;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;

        if (start === end && !event.shiftKey) {
            textarea.setRangeText('    ', start, end, 'end');
            dispatchEditorInput(textarea);
            return;
        }

        const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
        const nextBreak = value.indexOf('\n', end);
        const lineEnd = nextBreak === -1 ? value.length : nextBreak;
        const lines = value.slice(lineStart, lineEnd).split('\n');
        const transformed = lines.map(line => {
            if (!event.shiftKey) return `    ${line}`;
            return line.replace(/^ {1,4}/, '');
        }).join('\n');
        textarea.setRangeText(transformed, lineStart, lineEnd, 'select');
        dispatchEditorInput(textarea);
    }

    function insertUploadPlaceholder(fileName) {
        const token = `upload-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const label = String(fileName || '图片').replace(/[\[\]\r\n]/g, ' ').trim() || '图片';
        const placeholder = `![正在上传 ${label}…](Uploading-${token})`;
        const textarea = elements.content;
        const start = textarea.selectionStart;
        const needsLeadingBreak = start > 0 && textarea.value[start - 1] !== '\n';
        const insertion = `${needsLeadingBreak ? '\n' : ''}${placeholder}\n`;
        textarea.setRangeText(insertion, start, textarea.selectionEnd, 'end');
        textarea.focus();
        dispatchEditorInput(textarea);
        return { placeholder, label };
    }

    function finishUploadPlaceholder(upload, url) {
        const markdown = `![${upload.label}](${url})`;
        if (elements.content.value.includes(upload.placeholder)) {
            elements.content.value = elements.content.value.replace(upload.placeholder, markdown);
        } else {
            elements.content.value += `\n${markdown}\n`;
        }
        dispatchEditorInput(elements.content);
    }

    function removeUploadPlaceholder(upload) {
        elements.content.value = elements.content.value
            .replace(`${upload.placeholder}\n`, '')
            .replace(upload.placeholder, '');
        dispatchEditorInput(elements.content);
    }

    async function authenticatedFetch(url, options = {}) {
        const response = await window.fetch(url, options);
        if (response.status === 401) {
            saveDraftLocally();
            const returnTo = encodeURIComponent(
                `${window.location.pathname}${window.location.search}${window.location.hash}`
            );
            window.location.href = `/login?expired=1&next=${returnTo}`;
            throw new Error('AUTH_EXPIRED');
        }
        return response;
    }

    async function uploadImage(file) {
        const formData = new FormData();
        formData.append('file', file);
        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), IMAGE_UPLOAD_TIMEOUT_MS);
        try {
            const response = await authenticatedFetch('/api/upload', {
                method: 'POST',
                body: formData,
                signal: controller.signal
            });
            if (!response.ok) {
                let detail = '图片上传失败';
                try {
                    const data = await response.json();
                    detail = typeof data.detail === 'string' ? data.detail : detail;
                } catch (error) {
                    // 非 JSON 响应使用通用提示。
                }
                throw new Error(detail);
            }
            const data = await response.json();
            if (!data || typeof data.url !== 'string' || !isSafeUrl(data.url, { image: true })) {
                throw new Error('服务器返回了无效的图片地址');
            }
            return data.url;
        } catch (error) {
            if (error.name === 'AbortError') throw new Error('图片上传超过 60 秒，请重试');
            throw error;
        } finally {
            window.clearTimeout(timeoutId);
        }
    }

    async function uploadFiles(fileList) {
        const files = Array.from(fileList || []).filter(file => file && file.type.startsWith('image/'));
        if (!files.length) {
            setUploadStatus('请选择有效的图片文件', 'error');
            return;
        }

        if (state.pendingUploads === 0) {
            state.uploadFailureCount = 0;
            state.uploadWaveTotal = 0;
        }
        const uploads = files.map(file => ({ file, placeholder: insertUploadPlaceholder(file.name) }));
        state.pendingUploads += uploads.length;
        state.uploadWaveTotal += uploads.length;
        setControlsBusy();
        setUploadStatus(`正在上传 ${uploads.length} 张图片…`, 'active');

        const results = await Promise.allSettled(uploads.map(async upload => {
            const url = await uploadImage(upload.file);
            finishUploadPlaceholder(upload.placeholder, url);
            return upload.file.name;
        }));

        let failed = 0;
        results.forEach((result, index) => {
            if (result.status === 'rejected') {
                failed += 1;
                removeUploadPlaceholder(uploads[index].placeholder);
                if (result.reason?.message !== 'AUTH_EXPIRED') {
                    console.error(`图片 ${uploads[index].file.name} 上传失败：`, result.reason);
                }
            }
        });

        state.uploadFailureCount += failed;
        state.pendingUploads = Math.max(0, state.pendingUploads - uploads.length);
        setControlsBusy();
        if (state.pendingUploads > 0) {
            setUploadStatus(`仍有 ${state.pendingUploads} 张图片正在上传…`, 'active');
        } else if (state.uploadFailureCount) {
            setUploadStatus(`${state.uploadFailureCount} 张图片上传失败，请重试`, 'error');
        } else {
            setUploadStatus(`${state.uploadWaveTotal} 张图片上传完成`, 'success');
        }
    }

    function validateFields() {
        clearErrors();
        const fields = captureFields();
        const cleanContent = stripUploadPlaceholders(fields.content);
        if (cleanContent !== fields.content) {
            fields.content = cleanContent;
            elements.content.value = cleanContent;
            renderPreview();
            updateStats();
        }
        let firstInvalid = null;

        if (!fields.title.trim()) {
            setFieldError('title', '请输入文章标题。');
            firstInvalid = firstInvalid || elements.title;
        }
        if (!fields.content.trim()) {
            setFieldError('content', '请输入文章正文。');
            firstInvalid = firstInvalid || elements.content;
        }
        if (!fields.slug.trim()) {
            const generated = generateSlug(fields.title);
            if (generated) {
                elements.slug.value = generated;
                fields.slug = generated;
            } else {
                setFieldError('slug', '请输入有效的 URL 别名。');
                firstInvalid = firstInvalid || elements.slug;
            }
        }
        if (fields.slug && !/^[\p{L}\p{N}_]+(?:-[\p{L}\p{N}_]+)*$/u.test(fields.slug.trim())) {
            setFieldError('slug', '只能使用文字、数字、下划线和连接各段的连字符。');
            firstInvalid = firstInvalid || elements.slug;
        }
        if (!fields.category.trim()) {
            setFieldError('category', '请输入文章分类。');
            firstInvalid = firstInvalid || elements.category;
        }

        if (firstInvalid) {
            if ([elements.slug, elements.summary, elements.category, elements.tags].includes(firstInvalid)) {
                openSettings();
            } else if (firstInvalid === elements.content) {
                setEditorMode('write');
            }
            firstInvalid.focus();
            setSaveStatus('请先修正表单内容', 'error');
            return null;
        }

        return {
            title: fields.title.trim(),
            slug: fields.slug.trim().toLocaleLowerCase('zh-CN'),
            summary: fields.summary.trim() || null,
            category: fields.category.trim() || 'Tech',
            tags: fields.tags.trim(),
            content: fields.content
        };
    }

    async function showResponseErrors(response) {
        let data = null;
        try {
            data = await response.json();
        } catch (error) {
            // 非 JSON 响应在下方显示通用错误。
        }

        if (Array.isArray(data?.detail)) {
            let firstField = null;
            data.detail.forEach(issue => {
                const field = Array.isArray(issue.loc) ? issue.loc[issue.loc.length - 1] : null;
                if (field && elements[field]) {
                    setFieldError(field, issue.msg || '此字段不符合要求。');
                    firstField = firstField || field;
                }
            });
            if (firstField) {
                const target = elements[firstField];
                if ([elements.slug, elements.summary, elements.category, elements.tags].includes(target)) {
                    openSettings();
                } else if (target === elements.content) {
                    setEditorMode('write');
                }
                target.focus();
                return 'validation';
            }
        }

        const detail = typeof data?.detail === 'string' ? data.detail : '';
        if (response.status === 409 && /slug/i.test(detail)) {
            setFieldError('slug', '这个 URL 别名已被其他文章使用，请换一个。');
            openSettings();
            elements.slug.focus();
            return 'slug-conflict';
        }
        if (response.status === 409 || response.status === 412) {
            state.hasConflict = true;
            state.isDirty = true;
            setFormError(
                '文章已在另一个窗口或设备中更新，当前保存已被阻止。你的内容已保存在本机；请刷新页面加载最新版，再选择恢复本地草稿并重新保存。'
            );
            saveDraftLocally({ force: true });
            return 'version-conflict';
        }
        setFormError(detail || `保存失败（HTTP ${response.status}），请稍后重试。`);
        return 'general';
    }

    async function savePost(shouldPublish) {
        if (state.isSaving) return;
        if (state.pendingUploads > 0) {
            setSaveStatus('请等待图片上传完成', 'error');
            setUploadStatus('图片上传完成前不能保存或发布', 'error');
            return;
        }
        const payload = validateFields();
        if (!payload) return;
        if (
            state.isPublished &&
            !shouldPublish &&
            !window.confirm('撤回后访客将无法继续访问这篇文章。确定保存修改并撤回为草稿吗？')
        ) {
            return;
        }
        payload.is_published = Boolean(shouldPublish);

        state.isSaving = true;
        setControlsBusy();
        setSaveStatus(shouldPublish ? '正在发布…' : '正在保存草稿…', 'saving');
        const oldDraftKey = getDraftKey();

        try {
            const headers = { 'Content-Type': 'application/json' };
            if (state.postId && state.etag) headers['If-Match'] = state.etag;
            const response = await authenticatedFetch(
                state.postId ? `/api/posts/${state.postId}` : '/api/posts',
                {
                    method: state.postId ? 'PUT' : 'POST',
                    headers,
                    body: JSON.stringify(payload)
                }
            );
            if (!response.ok) {
                const errorKind = await showResponseErrors(response);
                setSaveStatus(
                    errorKind === 'version-conflict' ? '检测到版本冲突，本地稿已保留' : '保存失败，本地草稿仍在',
                    'error'
                );
                if (errorKind !== 'version-conflict') scheduleLocalSave();
                return;
            }

            state.etag = response.headers.get('ETag');
            const savedPost = await response.json();
            state.postId = savedPost.id;
            state.isNew = false;
            state.isPublished = Boolean(savedPost.is_published);
            state.lastSavedSlug = String(savedPost.slug || payload.slug);
            state.serverUpdatedAt = Date.parse(savedPost.updated_at || '') || Date.now();
            state.hasConflict = false;

            applyFields({ ...payload, ...savedPost });
            state.lastServerSnapshot = serializeFields();
            state.isDirty = false;
            state.slugManuallyEdited = true;

            safeStorageRemove(oldDraftKey);
            safeStorageRemove(getDraftKey());
            updatePublicationUI();
            updateViewLink();
            window.history.replaceState({}, '', `/admin/posts/${state.postId}/edit`);
            elements.localStatus.textContent = '服务器保存成功，本地临时草稿已清除';
            setSaveStatus(state.isPublished ? '已发布并保存' : '草稿已保存', 'saved');
        } catch (error) {
            if (error.message !== 'AUTH_EXPIRED') {
                console.error('文章保存失败：', error);
                setSaveStatus('网络异常，本地草稿仍在', 'offline');
                setFormError('暂时无法连接服务器，内容已保存在本机，请稍后重试。');
                saveDraftLocally();
            }
        } finally {
            state.isSaving = false;
            setControlsBusy();
        }
    }

    function setEditorMode(mode) {
        if (!['write', 'split', 'preview'].includes(mode)) return;
        elements.workspace.dataset.mode = mode;
        document.querySelectorAll('[data-editor-mode]').forEach(button => {
            const active = button.dataset.editorMode === mode;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-pressed', String(active));
        });
        if (mode !== 'write') renderPreview();
        try {
            window.localStorage.setItem(MODE_STORAGE_KEY, mode);
        } catch (error) {
            // 视图偏好保存失败不影响编辑器。
        }
    }

    function setMobilePanel(panel) {
        document.querySelectorAll('[data-mobile-panel]').forEach(button => {
            const active = button.dataset.mobilePanel === panel;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-selected', String(active));
        });
        if (panel === 'settings') {
            openSettings();
            return;
        }
        closeSettings({ restoreFocus: false, syncMobile: false });
        setEditorMode(panel === 'preview' ? 'preview' : 'write');
    }

    function openSettings() {
        if (elements.settingsDrawer.classList.contains('is-open')) return;
        state.settingsReturnFocus = document.activeElement instanceof HTMLElement
            ? document.activeElement
            : elements.settingsToggle;
        elements.settingsDrawer.classList.add('is-open');
        elements.settingsBackdrop.classList.add('is-open');
        elements.settingsDrawer.removeAttribute('inert');
        elements.settingsDrawer.setAttribute('aria-hidden', 'false');
        elements.settingsToggle.setAttribute('aria-expanded', 'true');
        document.body.classList.add('post-editor-settings-open');
        document.querySelectorAll('[data-mobile-panel]').forEach(button => {
            const active = button.dataset.mobilePanel === 'settings';
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-selected', String(active));
            if (button.dataset.mobilePanel === 'settings') button.setAttribute('aria-expanded', 'true');
        });
        window.setTimeout(() => elements.slug.focus(), 80);
    }

    function closeSettings(options = {}) {
        const restoreFocus = options.restoreFocus !== false;
        const syncMobile = options.syncMobile !== false;
        elements.settingsDrawer.classList.remove('is-open');
        elements.settingsBackdrop.classList.remove('is-open');
        elements.settingsDrawer.setAttribute('inert', '');
        elements.settingsDrawer.setAttribute('aria-hidden', 'true');
        elements.settingsToggle.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('post-editor-settings-open');
        if (syncMobile) {
            const currentPanel = elements.workspace.dataset.mode === 'preview' ? 'preview' : 'write';
            document.querySelectorAll('[data-mobile-panel]').forEach(button => {
                const active = button.dataset.mobilePanel === currentPanel;
                button.classList.toggle('is-active', active);
                button.setAttribute('aria-selected', String(active));
                if (button.dataset.mobilePanel === 'settings') button.setAttribute('aria-expanded', 'false');
            });
        }
        if (restoreFocus && state.settingsReturnFocus?.isConnected) {
            state.settingsReturnFocus.focus();
        }
    }

    function handleSettingsFocusTrap(event) {
        if (event.key !== 'Tab' || !elements.settingsDrawer.classList.contains('is-open')) return;
        const focusable = Array.from(elements.settingsDrawer.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href]'
        )).filter(element => element.getClientRects().length > 0);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    function generateSummaryFromContent() {
        const withoutCode = elements.content.value.replace(/```[\s\S]*?```/g, ' ');
        const blocks = withoutCode.split(/\n\s*\n/).map(raw => ({
            raw: raw.trim(),
            cleaned: raw
                .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
                .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
                .replace(/^\s{0,3}(?:#{1,6}|>|[-*+] |\d+\. )\s*/gm, '')
                .replace(/[*_~`]/g, '')
                .replace(/<[^>]*>/g, '')
                .replace(/\s+/g, ' ')
                .trim()
        })).filter(block => block.cleaned);
        const preferredBlock = blocks.find(block => !/^(?:#{1,6}\s|>|[-*+]\s|\d+\.\s|!\[)/.test(block.raw));
        const source = preferredBlock?.cleaned || blocks[0]?.cleaned || '';
        const characters = Array.from(source);
        elements.summary.value = characters.length > 240
            ? `${characters.slice(0, 239).join('')}…`
            : source;
        dispatchEditorInput(elements.summary);
        if (!source) setFieldError('summary', '正文中还没有可用于生成摘要的内容。');
    }

    function addTagSuggestion(tag) {
        if (!tag) return;
        const existing = elements.tags.value.split(',').map(item => item.trim()).filter(Boolean);
        if (!existing.some(item => item.toLocaleLowerCase() === tag.toLocaleLowerCase())) {
            existing.push(tag);
            elements.tags.value = existing.join(', ');
            dispatchEditorInput(elements.tags);
        }
        elements.tags.focus();
    }

    function handleGlobalShortcut(event) {
        const commandKey = event.metaKey || event.ctrlKey;
        if (!commandKey) return;
        const key = event.key.toLocaleLowerCase();
        if (key === 's') {
            event.preventDefault();
            event.stopImmediatePropagation();
            savePost(state.isPublished);
            return;
        }
        if (event.target !== elements.content) return;
        if (key === 'b' || key === 'k') {
            event.preventDefault();
            event.stopImmediatePropagation();
            insertMarkdown(key === 'b' ? 'bold' : 'link');
        }
    }

    async function loadExistingPost() {
        if (!state.postId) return;
        setSaveStatus('正在加载文章…', 'saving');
        try {
            const response = await authenticatedFetch(`/api/posts/${state.postId}`);
            if (!response.ok) {
                let detail = '文章加载失败，请返回后台重试。';
                try {
                    const data = await response.json();
                    if (typeof data.detail === 'string') detail = data.detail;
                } catch (error) {
                    // 使用通用错误信息。
                }
                throw new Error(detail);
            }
            state.etag = response.headers.get('ETag');
            const post = await response.json();
            applyFields(post);
            state.isPublished = Boolean(post.is_published);
            state.hasConflict = false;
            state.lastSavedSlug = String(post.slug || '');
            state.serverUpdatedAt = Date.parse(post.updated_at || '') || 0;
            state.slugManuallyEdited = true;
            state.lastServerSnapshot = serializeFields();
            state.isDirty = false;
            updatePublicationUI();
            updateViewLink();
            setSaveStatus(
                state.isPublished ? '已发布 · Ctrl+S 会直接更新线上文章' : '草稿已加载',
                'saved'
            );
        } catch (error) {
            if (error.message !== 'AUTH_EXPIRED') {
                console.error('文章加载失败：', error);
                setFormError(error.message || '文章加载失败，请返回后台重试。');
                setSaveStatus('文章加载失败', 'error');
            }
        }
    }

    function bindEvents() {
        elements.form.addEventListener('submit', event => event.preventDefault());
        elements.form.addEventListener('input', handleEditorInput);

        document.querySelectorAll('.post-editor-save-draft').forEach(button => {
            button.addEventListener('click', () => savePost(false));
        });
        document.querySelectorAll('.post-editor-publish').forEach(button => {
            button.addEventListener('click', () => savePost(true));
        });
        document.querySelectorAll('[data-editor-mode]').forEach(button => {
            button.addEventListener('click', () => setEditorMode(button.dataset.editorMode));
        });
        document.querySelectorAll('[data-mobile-panel]').forEach(button => {
            button.addEventListener('click', () => setMobilePanel(button.dataset.mobilePanel));
        });
        document.querySelectorAll('[data-markdown-action]').forEach(button => {
            button.addEventListener('click', () => insertMarkdown(button.dataset.markdownAction));
        });
        document.querySelectorAll('[data-category-suggestion]').forEach(button => {
            button.addEventListener('click', () => {
                elements.category.value = button.dataset.categorySuggestion || '';
                dispatchEditorInput(elements.category);
                elements.category.focus();
            });
        });
        document.querySelectorAll('[data-tag-suggestion]').forEach(button => {
            button.addEventListener('click', () => addTagSuggestion(button.dataset.tagSuggestion || ''));
        });

        elements.settingsToggle.addEventListener('click', openSettings);
        elements.settingsClose.addEventListener('click', () => closeSettings());
        elements.settingsBackdrop.addEventListener('click', () => closeSettings());
        elements.settingsDrawer.addEventListener('keydown', handleSettingsFocusTrap);
        elements.generateSummary.addEventListener('click', generateSummaryFromContent);
        elements.restoreDraft.addEventListener('click', restoreLocalDraft);
        elements.discardDraft.addEventListener('click', discardLocalDraft);

        elements.imageInput.addEventListener('change', () => {
            uploadFiles(elements.imageInput.files);
            elements.imageInput.value = '';
        });
        elements.content.addEventListener('paste', event => {
            const imageFiles = Array.from(event.clipboardData?.items || [])
                .filter(item => item.type.startsWith('image/'))
                .map(item => item.getAsFile())
                .filter(Boolean);
            if (!imageFiles.length) return;
            event.preventDefault();
            uploadFiles(imageFiles);
        });
        elements.content.addEventListener('dragover', event => {
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
            elements.content.classList.add('is-dragging');
            setUploadStatus('松开鼠标上传图片', 'active');
        });
        elements.content.addEventListener('dragleave', event => {
            if (event.relatedTarget && elements.content.contains(event.relatedTarget)) return;
            elements.content.classList.remove('is-dragging');
            if (!state.pendingUploads) setUploadStatus('可粘贴、拖拽或选择图片');
        });
        elements.content.addEventListener('drop', event => {
            event.preventDefault();
            elements.content.classList.remove('is-dragging');
            uploadFiles(event.dataTransfer?.files);
        });
        elements.content.addEventListener('keydown', event => {
            if (event.key === 'Tab') indentSelection(event);
        });
        elements.title.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                elements.content.focus();
            }
        });
        elements.content.addEventListener('scroll', () => {
            if (elements.workspace.dataset.mode !== 'split') return;
            window.cancelAnimationFrame(state.scrollSyncFrame);
            state.scrollSyncFrame = window.requestAnimationFrame(() => {
                const sourceMax = elements.content.scrollHeight - elements.content.clientHeight;
                const previewMax = elements.preview.scrollHeight - elements.preview.clientHeight;
                if (sourceMax > 0 && previewMax > 0) {
                    elements.preview.scrollTop = (elements.content.scrollTop / sourceMax) * previewMax;
                }
            });
        });

        window.addEventListener('keydown', handleGlobalShortcut, true);
        window.addEventListener('keydown', event => {
            if (event.key === 'Escape' && elements.settingsDrawer.classList.contains('is-open')) {
                event.preventDefault();
                closeSettings();
            }
        });
        window.addEventListener('beforeunload', event => {
            saveDraftLocally();
            if (!state.isDirty || state.isSaving) return;
            event.preventDefault();
            event.returnValue = '';
        });
        window.addEventListener('pagehide', () => saveDraftLocally());
        window.addEventListener('online', () => {
            if (state.isDirty) setSaveStatus('网络已恢复，仍有未保存修改', 'dirty');
        });
        window.addEventListener('offline', () => {
            if (state.isDirty) setSaveStatus('当前离线，修改仅保存在本机', 'offline');
        });
    }

    async function initialize() {
        bindEvents();
        setControlsBusy();
        updateStats();
        autoResizeTitle();

        const savedMode = safeStorageGet(MODE_STORAGE_KEY);
        const initialMode = state.isNew
            ? 'write'
            : (['write', 'split', 'preview'].includes(savedMode) ? savedMode : 'write');
        setEditorMode(initialMode);

        if (state.postId) {
            await loadExistingPost();
        } else {
            state.isPublished = false;
            state.slugManuallyEdited = false;
            state.lastServerSnapshot = serializeFields();
            state.serverUpdatedAt = 0;
            updatePublicationUI();
            setSaveStatus('新文章将默认保存为草稿', 'idle');
            renderPreview();
        }

        state.isLoading = false;
        app.setAttribute('aria-busy', 'false');
        setControlsBusy();
        offerLocalDraftIfNeeded();
        if (!state.postId && !state.pendingRestore) elements.title.focus();
    }

    initialize();
})();
