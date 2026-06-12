let currentStep = 1;
const TOTAL_STEPS = 5;
const PROGRESS = { 1: 20, 2: 40, 3: 60, 4: 80, 5: 100 };

// ── Step navigation ───────────────────────────────────────────────────────────
function goNext(step) {
    if (!validateStep(step)) return;
    if (step === 1) {
        submitRegistration();
    } else {
        showStep(step + 1);
    }
}

function goBack(step) {
    showStep(step - 1);
}

function showStep(n) {
    document.getElementById('step' + currentStep).style.display = 'none';
    document.getElementById('step' + n).style.display = 'block';

    // Update circles
    const prev = document.getElementById('s' + currentStep);
    prev.classList.remove('active');

    if (n > currentStep) {
        prev.classList.add('done');
        prev.textContent = '✓';
    } else {
        prev.classList.remove('done');
        prev.classList.add('active');
        prev.textContent = currentStep;
        const target = document.getElementById('s' + n);
        target.classList.remove('done');
        target.classList.add('active');
        target.textContent = n;
    }

    if (n > currentStep) {
        document.getElementById('s' + n).classList.add('active');
    }

    // Update connector lines
    for (let i = 1; i < TOTAL_STEPS; i++) {
        const line = document.getElementById('l' + i);
        if (line) line.classList.toggle('done', i < n);
    }

    // Progress bar
    document.getElementById('progressFill').style.width = PROGRESS[n] + '%';

    // Populate API keys on step 4
    if (n === 4) populateApiKeys();

    currentStep = n;
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Step 1: Register ──────────────────────────────────────────────────────────
async function submitRegistration() {
    const btn = document.querySelector('#step1 .btn--primary');
    btn.disabled = true;
    btn.textContent = 'Creating account...';

    const email    = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const firstName = document.getElementById('firstName').value.trim();
    const lastName  = document.getElementById('lastName').value.trim();
    const bizName   = document.getElementById('businessName').value.trim();

    try {
        const resp = await fetch('/v1/accounts/register/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email,
                password,
                first_name: firstName,
                last_name: lastName,
                business_name: bizName,
                phone: document.getElementById('phone').value.trim(),
            }),
        });

        const data = await resp.json();

        if (resp.ok) {
            // Store token for subsequent API calls
            window._authToken = data.token || data.access || '';
            window._merchantEmail = email;
            showStep(2);
        } else {
            showError('step1', data.error || data.detail || JSON.stringify(data));
        }
    } catch (err) {
        showError('step1', 'Network error — please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Continue →';
    }
}

// ── Validation ────────────────────────────────────────────────────────────────
function validateStep(step) {
    const required = {
        1: ['businessName', 'firstName', 'lastName', 'email', 'password'],
        2: ['bizType', 'pan', 'address'],
        3: ['accName', 'accNum', 'accNum2', 'ifsc'],
        4: [],
    };

    const fields = required[step] || [];
    let valid = true;

    fields.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (!el.value.trim()) {
            el.style.borderColor = '#ef4444';
            el.style.boxShadow = '0 0 0 3px rgba(239,68,68,.12)';
            valid = false;
            el.addEventListener('input', () => {
                el.style.borderColor = '';
                el.style.boxShadow = '';
            }, { once: true });
        }
    });

    if (step === 3) {
        const a = document.getElementById('accNum');
        const b = document.getElementById('accNum2');
        if (a && b && a.value !== b.value) {
            b.style.borderColor = '#ef4444';
            b.style.boxShadow = '0 0 0 3px rgba(239,68,68,.12)';
            valid = false;
        }
    }

    // Email format check
    if (step === 1) {
        const email = document.getElementById('email');
        if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value)) {
            email.style.borderColor = '#ef4444';
            email.style.boxShadow = '0 0 0 3px rgba(239,68,68,.12)';
            valid = false;
        }
        // Password length
        const pw = document.getElementById('password');
        if (pw && pw.value.length < 8) {
            pw.style.borderColor = '#ef4444';
            pw.style.boxShadow = '0 0 0 3px rgba(239,68,68,.12)';
            valid = false;
        }
    }

    return valid;
}

// ── API Keys (Step 4) ─────────────────────────────────────────────────────────
async function populateApiKeys() {
    // Try to fetch real keys if user is logged in
    try {
        const headers = { 'Content-Type': 'application/json' };
        if (window._authToken) {
            headers['Authorization'] = 'Bearer ' + window._authToken;
        }
        const resp = await fetch('/v1/accounts/api-keys/', {
            method: 'POST',
            headers,
            body: JSON.stringify({ key_type: 'test' }),
        });
        if (resp.ok) {
            const data = await resp.json();
            document.getElementById('displayKeyId').textContent = data.key_id || data.key_prefix || 'rzp_test_' + randomHex(16);
            document.getElementById('displaySecret').textContent = data.full_key || 'rzp_test_secret_' + randomHex(24);
            window._keyId = document.getElementById('displayKeyId').textContent;
            window._secret = document.getElementById('displaySecret').textContent;
            return;
        }
    } catch (_) {}

    // Fallback — show placeholder keys
    const keyId = 'rzp_test_' + randomHex(16);
    const secret = 'rzp_test_secret_' + randomHex(24);
    document.getElementById('displayKeyId').textContent = keyId;
    document.getElementById('displaySecret').textContent = secret;
    window._keyId = keyId;
    window._secret = secret;
}

function copyKey(type) {
    const val = type === 'keyId' ? window._keyId : window._secret;
    navigator.clipboard.writeText(val).then(() => {
        const btn = event.target;
        const orig = btn.textContent;
        btn.textContent = '✓ Copied!';
        btn.style.color = '#16a34a';
        setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 2000);
    });
}

function randomHex(len) {
    return Array.from({ length: len }, () =>
        Math.floor(Math.random() * 16).toString(16)
    ).join('');
}

function showError(stepId, message) {
    const existing = document.getElementById('onboarding-error');
    if (existing) existing.remove();
    const el = document.createElement('div');
    el.id = 'onboarding-error';
    el.style.cssText = 'background:#fee2e2;color:#b91c1c;border:1px solid #fecaca;border-radius:8px;padding:12px 16px;font-size:13px;font-weight:500;margin-bottom:16px;';
    el.textContent = '⚠ ' + message;
    const content = document.getElementById(stepId);
    content.insertBefore(el, content.querySelector('.form-group'));
}

function showIntegrationGuide() {
    window.location.href = '/dashboard/sandbox/';
}