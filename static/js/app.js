function app() {
    return {
        // Questionnaire state
        testStarted: false,
        testCompleted: false,
        currentQuestion: 0,
        answers: [],
        questions: [],
        // Upload/Image state
        uploadStarted: false,
        uploadFile: null,
        uploadPreview: null,
        uploading: false,
        // Result
        result: {},

        async init() {
            try {
                const response = await fetch('/api/questions');
                const data = await response.json();
                this.questions = data.questions || [];
            } catch (error) {
                console.error('Error loading questions:', error);
            }
        },

        // Questionnaire flow
        startTest() {
            this.testStarted = true;
            this.uploadStarted = false;
            this.testCompleted = false;
            this.currentQuestion = 0;
            this.answers = [];
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        async answerQuestion(answer) {
            this.answers.push(answer);
            if (this.currentQuestion < this.questions.length - 1) {
                this.currentQuestion++;
                document.querySelector('main')?.scrollIntoView({ behavior: 'smooth' });
            } else {
                await this.submitTest();
            }
        },

        async submitTest() {
            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        answers: this.answers,
                        name: 'Khotso Edwin Matlatsa'
                    })
                });
                this.result = await response.json();
                this.testCompleted = true;
                this.testStarted = false;
                setTimeout(() => document.querySelector('[x-show="testCompleted"]')?.scrollIntoView({ behavior: 'smooth' }), 200);
            } catch (error) {
                console.error('Error submitting test:', error);
                alert('An error occurred while processing your test. Please try again.');
            }
        },

        // Upload flow
        startUpload() {
            this.uploadStarted = true;
            this.testStarted = false;
            this.testCompleted = false;
            this.uploadFile = null;
            this.uploadPreview = null;
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        handleFileChange(evt) {
            const file = evt.target.files?.[0];
            this.uploadFile = file || null;
            if (file) {
                const reader = new FileReader();
                reader.onload = e => { this.uploadPreview = e.target.result; };
                reader.readAsDataURL(file);
            } else {
                this.uploadPreview = null;
            }
        },

        async submitImage() {
            if (!this.uploadFile) return;
            this.uploading = true;
            try {
                const form = new FormData();
                form.append('image', this.uploadFile);
                form.append('name', 'Khotso Edwin Matlatsa');
                const res = await fetch('/api/analyze_image', { method: 'POST', body: form });
                const data = await res.json();
                if (!res.ok) throw new Error(data?.error || 'Upload failed');
                this.result = data;
                this.testCompleted = true;
                this.uploadStarted = false;
                setTimeout(() => document.querySelector('[x-show="testCompleted"]')?.scrollIntoView({ behavior: 'smooth' }), 200);
            } catch (e) {
                console.error(e);
                alert('Failed to analyze image. ' + (e?.message || ''));
            } finally {
                this.uploading = false;
            }
        },

        restartTest() {
            this.testStarted = false;
            this.uploadStarted = false;
            this.testCompleted = false;
            this.currentQuestion = 0;
            this.answers = [];
            this.uploadFile = null;
            this.uploadPreview = null;
            this.result = {};
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    };
}

// Sliding page transitions
(function() {
    function sameOrigin(url) {
        try { const u = new URL(url, window.location.href); return u.origin === window.location.origin; } catch { return false; }
    }
    function setup() {
        const overlay = document.getElementById('transitionOverlay');
        if (!overlay) return;
        // Entrance animation
        requestAnimationFrame(() => {
            overlay.classList.add('in');
            setTimeout(() => overlay.classList.add('out'), 30);
        });
        // Intercept internal link clicks
        document.addEventListener('click', (e) => {
            const a = e.target.closest('a');
            if (!a) return;
            if (a.hasAttribute('download') || a.target === '_blank' || a.getAttribute('rel') === 'external' || a.dataset.noTransition === 'true') return;
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            const href = a.getAttribute('href');
            if (!href || href.startsWith('#') || !sameOrigin(href)) return;
            e.preventDefault();
            overlay.classList.remove('out');
            overlay.classList.add('in');
            setTimeout(() => { window.location.href = href; }, 320);
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup); else setup();
})();

// Form UX enhancements: toasts, inline validation, submit guards
(function() {
    function ready(fn){ if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',fn);} else {fn();} }

    // Toasts
    const Toast = (() => {
        let container;
        function ensureContainer(){
            if (!container) {
                container = document.createElement('div');
                container.className = 'toast-container';
                document.body.appendChild(container);
            }
            return container;
        }
        function show({ title = '', desc = '', type = 'success', timeout = 3500 } = {}){
            const c = ensureContainer();
            const el = document.createElement('div');
            el.className = `toast ${type}`;
            el.innerHTML = `<div class="title">${title || (type==='success'?'Success':'Error')}</div>${desc?`<div class="desc">${desc}</div>`:''}`;
            c.appendChild(el);
            const t = setTimeout(() => { el.remove(); }, timeout);
            el.addEventListener('click', () => { clearTimeout(t); el.remove(); });
        }
        return { show };
    })();

    // Convert Flask flash alerts into toasts if present
    function migrateFlashToToasts() {
        // look for alert blocks used in templates (bg-red-50 / bg-green-50)
        const alerts = Array.from(document.querySelectorAll('.bg-red-50, .bg-green-50'));
        if (!alerts.length) return;
        alerts.forEach(el => {
            const text = el.textContent.trim();
            const isError = el.classList.contains('bg-red-50');
            Toast.show({ type: isError ? 'error' : 'success', title: isError ? 'Error' : 'Success', desc: text });
        });
        // remove the original alert container parent block to reduce clutter
        const container = alerts[0]?.parentElement;
        if (container) container.remove();
    }

    // Inline validation helpers
    function ensureErrorEl(input) {
        let err = input.parentElement.querySelector('.form-error');
        if (!err) {
            err = document.createElement('p');
            err.className = 'form-error';
            input.parentElement.appendChild(err);
        }
        return err;
    }
    function clearError(input) {
        const err = input.parentElement.querySelector('.form-error');
        if (err) err.textContent = '';
        input.classList.remove('is-invalid');
    }
    function showError(input, message) {
        const err = ensureErrorEl(input);
        err.textContent = message || input.validationMessage || 'Invalid value';
        input.classList.add('is-invalid');
    }

    function validateInput(input) {
        clearError(input);
        if (input.willValidate && !input.checkValidity()) {
            showError(input);
            return false;
        }
        return true;
    }

    function enhanceForms() {
        const forms = Array.from(document.querySelectorAll('form[method="POST"], form[method="post"], form:not([method])'));
        if (!forms.length) return;

        forms.forEach(form => {
            const inputs = Array.from(form.querySelectorAll('input, select, textarea'));

            // Add sensible defaults without editing templates
            const email = form.querySelector('input[type="email"][name="email"]');
            const password = form.querySelector('input[type="password"][name="password"]');
            if (email && !email.required) email.required = true;
            if (password && !password.minLength) password.minLength = 6;

            inputs.forEach(inp => {
                inp.addEventListener('blur', () => validateInput(inp));
                inp.addEventListener('input', () => { if (inp.classList.contains('is-invalid')) validateInput(inp); });
            });

            // Focus management: first invalid or first input
            const invalid = inputs.find(i => i.willValidate && !i.checkValidity());
            (invalid || inputs[0])?.focus?.();

            // Submit guard and inline validation
            form.addEventListener('submit', (e) => {
                let ok = true;
                inputs.forEach(inp => { if (!validateInput(inp)) ok = false; });
                if (!ok) {
                    e.preventDefault();
                    const firstBad = inputs.find(inp => inp.classList.contains('is-invalid'));
                    firstBad?.focus?.();
                    Toast.show({ type: 'error', title: 'Please fix errors', desc: 'Some fields need your attention.' });
                    return;
                }

                // Disable submit button and indicate progress (let normal navigation occur)
                const submitBtn = form.querySelector('button[type="submit"], button:not([type]), input[type="submit"]');
                if (submitBtn) {
                    submitBtn.setAttribute('disabled', 'true');
                    submitBtn.dataset.originalText = submitBtn.textContent;
                    submitBtn.textContent = 'Please wait…';
                }
            });
        });
    }

    // Password visibility toggles
    function addPasswordToggles() {
        const pwFields = Array.from(document.querySelectorAll('input[type="password"]'));
        pwFields.forEach(input => {
            // Avoid duplicate toggles
            if (input.dataset.hasToggle === 'true') return;
            input.dataset.hasToggle = 'true';
            const wrap = input.parentElement;
            if (!wrap) return;
            // Ensure positioning context for absolute button
            if (getComputedStyle(wrap).position === 'static') {
                wrap.style.position = 'relative';
            }
            // Add right padding so text doesn't overlap the button
            input.style.paddingRight = '2.25rem';
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'password-toggle';
            btn.setAttribute('aria-label', 'Toggle password visibility');
            btn.textContent = 'Show';
            btn.addEventListener('click', () => {
                const isPw = input.type === 'password';
                input.type = isPw ? 'text' : 'password';
                btn.textContent = isPw ? 'Hide' : 'Show';
            });
            wrap.appendChild(btn);
        });
    }

    // Simple password strength estimation
    function estimateStrength(pw) {
        let score = 0;
        if (!pw) return 0;
        if (pw.length >= 6) score++;
        if (pw.length >= 10) score++;
        if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
        if (/\d/.test(pw) && /[^\w\s]/.test(pw)) score++;
        return Math.min(score, 4);
    }

    function addStrengthMeter() {
        // Only on Register page (heuristics)
        const isRegister = /register/i.test(document.title) || /register/.test(window.location.pathname);
        if (!isRegister) return;
        const input = document.querySelector('form input[type="password"][name="password"]');
        if (!input) return;
        // Avoid duplicate meters
        if (input.dataset.hasStrength === 'true') return;
        input.dataset.hasStrength = 'true';
        const wrap = document.createElement('div');
        wrap.className = 'strength-wrap';
        const meter = document.createElement('div');
        meter.className = 'strength-meter';
        const bar = document.createElement('div');
        bar.className = 'bar';
        meter.appendChild(bar);
        const label = document.createElement('div');
        label.className = 'strength-label';
        label.textContent = 'Strength: Weak';
        wrap.appendChild(meter);
        wrap.appendChild(label);
        // Insert after the password input
        input.parentElement.appendChild(wrap);

        function update() {
            const s = estimateStrength(input.value);
            meter.className = 'strength-meter';
            wrap.classList.remove('strength-0','strength-1','strength-2','strength-3','strength-4');
            wrap.classList.add(`strength-${s}`);
            const labels = ['Very weak','Weak','Fair','Strong','Very strong'];
            label.textContent = `Strength: ${labels[s]}`;
        }
        input.addEventListener('input', update);
        update();
    }

    ready(() => {
        migrateFlashToToasts();
        enhanceForms();
        addPasswordToggles();
        addStrengthMeter();
    });
})();

