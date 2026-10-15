// Multi-Step Registration Engine with Real Email OTP and Aadhaar Card Verification

document.addEventListener('DOMContentLoaded', function () {
    const roleInput = document.getElementById('register-role');
    if (!roleInput) return; // Not on registration page

    const userRole = roleInput.value; // 'owner' or 'tenant'

    // Steps containers
    const step1Box = document.getElementById('step-1-box');
    const step2Box = document.getElementById('step-2-box');
    const step3Box = document.getElementById('step-3-box');

    // Indicators
    const stepInd1 = document.getElementById('ind-step-1');
    const stepInd2 = document.getElementById('ind-step-2');
    const stepInd3 = document.getElementById('ind-step-3');

    // Registration state
    const regState = {
        role: userRole,
        email: '',
        emailVerified: false,
        aadhaar: '',
        maskedAadhaar: '',
        aadhaarSessionId: '',
        aadhaarVerified: false
    };

    // Helper: Show status notification
    function showMsg(containerId, message, isError = false) {
        const el = document.getElementById(containerId);
        if (!el) return;
        el.className = isError ? 'alert alert-danger' : 'alert alert-success';
        el.innerHTML = message;
        el.style.display = 'block';
    }

    function clearMsg(containerId) {
        const el = document.getElementById(containerId);
        if (el) el.style.display = 'none';
    }

    // ---------------------------------------------------------
    // STEP 1: EMAIL OTP VERIFICATION
    // ---------------------------------------------------------
    const btnSendEmailOtp = document.getElementById('btn-send-email-otp');
    const emailInput = document.getElementById('reg-email');
    const emailOtpSection = document.getElementById('email-otp-section');
    const btnVerifyEmailOtp = document.getElementById('btn-verify-email-otp');
    const emailOtpInput = document.getElementById('reg-email-otp');

    if (btnSendEmailOtp) {
        btnSendEmailOtp.addEventListener('click', async function () {
            clearMsg('step1-alert');
            const email = emailInput.value.trim();
            if (!email || !email.includes('@')) {
                showMsg('step1-alert', 'Please enter a valid email address.', true);
                return;
            }

            btnSendEmailOtp.disabled = true;
            btnSendEmailOtp.innerHTML = 'Sending Real OTP...';

            try {
                const res = await fetch('/api/auth/send-email-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: email, purpose: `${userRole}_registration` })
                });
                const data = await res.json();

                if (data.success) {
                    regState.email = email;
                    emailOtpSection.style.display = 'block';
                    emailInput.disabled = true;
                    btnSendEmailOtp.style.display = 'none';

                    let notice = '';
                    if (data.dispatched) {
                        notice = `A real 6-digit OTP has been dispatched to <strong>${email}</strong>. Please check your inbox or spam folder.`;
                    } else if (data.dev_hint) {
                        notice = `Verification code generated for <strong>${email}</strong>.<br>
                        <div style="margin-top: 8px; background: #fffbeb; padding: 10px 12px; border-radius: 6px; border: 1px solid #fde68a; color: #92400e; font-size: 0.85rem;">
                            <strong>SMTP Server Not Connected:</strong> Real emails require SMTP mail server credentials in Admin settings.<br>
                            For testing right now, your OTP code is: <span style="font-size: 1.15rem; font-weight: 800; font-family: monospace; letter-spacing: 2px; color: #1e40af; background: #eff6ff; padding: 2px 8px; border-radius: 4px;">${data.dev_hint}</span><br>
                            <small style="color: #64748b;">(To deliver live emails to your inbox, configure your Gmail App Password in Admin Dashboard > SMTP Settings).</small>
                        </div>`;
                    } else {
                        notice = `A 6-digit OTP has been generated for <strong>${email}</strong>.`;
                    }
                    showMsg('step1-alert', notice, false);
                } else {
                    showMsg('step1-alert', data.error || 'Failed to dispatch email OTP.', true);
                    btnSendEmailOtp.disabled = false;
                    btnSendEmailOtp.innerHTML = 'Send Email OTP';
                }
            } catch (err) {
                showMsg('step1-alert', 'Network error. Could not connect to mail server.', true);
                btnSendEmailOtp.disabled = false;
                btnSendEmailOtp.innerHTML = 'Send Email OTP';
            }
        });
    }

    if (btnVerifyEmailOtp) {
        btnVerifyEmailOtp.addEventListener('click', async function () {
            clearMsg('step1-alert');
            const otp = emailOtpInput.value.trim();
            if (!otp || otp.length < 6) {
                showMsg('step1-alert', 'Please enter the 6-digit OTP sent to your email.', true);
                return;
            }

            btnVerifyEmailOtp.disabled = true;
            btnVerifyEmailOtp.innerHTML = 'Verifying...';

            try {
                const res = await fetch('/api/auth/verify-email-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: regState.email, otp: otp, purpose: `${userRole}_registration` })
                });
                const data = await res.json();

                if (data.success) {
                    regState.emailVerified = true;
                    showMsg('step1-alert', 'Email verified successfully! Moving to Step 2: Aadhaar ID Verification...', false);

                    setTimeout(() => {
                        // Advance to Step 2
                        step1Box.style.display = 'none';
                        step2Box.style.display = 'block';
                        stepInd1.className = 'step-item completed';
                        stepInd2.className = 'step-item active';
                    }, 900);
                } else {
                    showMsg('step1-alert', data.error || 'Invalid OTP code.', true);
                    btnVerifyEmailOtp.disabled = false;
                    btnVerifyEmailOtp.innerHTML = 'Verify OTP';
                }
            } catch (err) {
                showMsg('step1-alert', 'Verification failed due to a network error.', true);
                btnVerifyEmailOtp.disabled = false;
                btnVerifyEmailOtp.innerHTML = 'Verify OTP';
            }
        });
    }

    // ---------------------------------------------------------
    // STEP 2: AADHAAR CARD OTP VERIFICATION
    // ---------------------------------------------------------
    const btnSendAadhaarOtp = document.getElementById('btn-send-aadhaar-otp');
    const aadhaarInput = document.getElementById('reg-aadhaar');
    const aadhaarOtpSection = document.getElementById('aadhaar-otp-section');
    const btnVerifyAadhaarOtp = document.getElementById('btn-verify-aadhaar-otp');
    const aadhaarOtpInput = document.getElementById('reg-aadhaar-otp');
    const linkedMobileText = document.getElementById('aadhaar-linked-mobile-text');

    if (btnSendAadhaarOtp) {
        btnSendAadhaarOtp.addEventListener('click', async function () {
            clearMsg('step2-alert');
            const rawAadhaar = aadhaarInput.value.replace(/[\s-]/g, '');

            if (!/^[2-9]{1}[0-9]{11}$/.test(rawAadhaar)) {
                showMsg('step2-alert', 'Please enter a valid 12-digit Indian Aadhaar number (cannot start with 0 or 1).', true);
                return;
            }

            btnSendAadhaarOtp.disabled = true;
            btnSendAadhaarOtp.innerHTML = 'Requesting UIDAI OTP...';

            try {
                const res = await fetch('/api/auth/send-aadhaar-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ aadhaar: rawAadhaar })
                });
                const data = await res.json();

                if (data.success) {
                    regState.aadhaar = rawAadhaar;
                    regState.maskedAadhaar = data.masked_aadhaar;
                    regState.aadhaarSessionId = data.session_id;

                    aadhaarInput.disabled = true;
                    btnSendAadhaarOtp.style.display = 'none';
                    aadhaarOtpSection.style.display = 'block';

                    linkedMobileText.innerHTML = `OTP dispatched to registered mobile: <strong>${data.linked_mobile}</strong>`;

                    let messageText = data.message;
                    if (data.sandbox_hint) {
                        messageText += ` <span style="background: #e2e8f0; padding: 2px 6px; border-radius: 4px; font-size: 0.82rem; font-family: monospace;">UIDAI Sandbox OTP: ${data.sandbox_hint}</span>`;
                    }
                    showMsg('step2-alert', messageText, false);
                } else {
                    showMsg('step2-alert', data.error || 'Failed to initiate Aadhaar OTP verification.', true);
                    btnSendAadhaarOtp.disabled = false;
                    btnSendAadhaarOtp.innerHTML = 'Send Aadhaar OTP';
                }
            } catch (err) {
                showMsg('step2-alert', 'Network error reaching UIDAI verification gateway.', true);
                btnSendAadhaarOtp.disabled = false;
                btnSendAadhaarOtp.innerHTML = 'Send Aadhaar OTP';
            }
        });
    }

    if (btnVerifyAadhaarOtp) {
        btnVerifyAadhaarOtp.addEventListener('click', async function () {
            clearMsg('step2-alert');
            const otp = aadhaarOtpInput.value.trim();
            if (!otp || otp.length < 6) {
                showMsg('step2-alert', 'Please enter the 6-digit Aadhaar OTP sent to your linked mobile.', true);
                return;
            }

            btnVerifyAadhaarOtp.disabled = true;
            btnVerifyAadhaarOtp.innerHTML = 'Validating with UIDAI...';

            try {
                const res = await fetch('/api/auth/verify-aadhaar-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: regState.aadhaarSessionId, otp: otp })
                });
                const data = await res.json();

                if (data.success) {
                    regState.aadhaarVerified = true;
                    showMsg('step2-alert', `Aadhaar ID ${data.masked_aadhaar} verified successfully! Proceeding to account profile setup...`, false);

                    setTimeout(() => {
                        // Advance to Step 3
                        step2Box.style.display = 'none';
                        step3Box.style.display = 'block';
                        stepInd2.className = 'step-item completed';
                        stepInd3.className = 'step-item active';

                        // Fill verified badges
                        const verifiedEmailBadge = document.getElementById('final-verified-email');
                        if (verifiedEmailBadge) verifiedEmailBadge.innerText = regState.email;

                        const verifiedAadhaarBadge = document.getElementById('final-verified-aadhaar');
                        if (verifiedAadhaarBadge) verifiedAadhaarBadge.innerText = regState.maskedAadhaar;
                    }, 900);
                } else {
                    showMsg('step2-alert', data.error || 'Invalid Aadhaar OTP code.', true);
                    btnVerifyAadhaarOtp.disabled = false;
                    btnVerifyAadhaarOtp.innerHTML = 'Verify Aadhaar OTP';
                }
            } catch (err) {
                showMsg('step2-alert', 'Error verifying Aadhaar OTP.', true);
                btnVerifyAadhaarOtp.disabled = false;
                btnVerifyAadhaarOtp.innerHTML = 'Verify Aadhaar OTP';
            }
        });
    }

    // Live password complexity validator
    const pwInput = document.getElementById('reg-password');
    const ruleLength = document.getElementById('rule-length');
    const ruleLetter = document.getElementById('rule-letter');
    const ruleDigit = document.getElementById('rule-digit');
    const ruleSpecial = document.getElementById('rule-special');

    function checkPasswordComplexity(pw) {
        const hasLength = pw.length >= 8;
        const hasLetter = /[A-Za-z]/.test(pw);
        const hasDigit = /\d/.test(pw);
        const hasSpecial = /[^A-Za-z0-9]/.test(pw);

        if (ruleLength) {
            ruleLength.innerHTML = hasLength ? '<i class="fa-solid fa-circle-check" style="color:#10b981;"></i> At least 8 characters' : '<i class="fa-solid fa-circle-xmark" style="color:#ef4444;"></i> At least 8 characters';
            ruleLength.style.color = hasLength ? '#047857' : '#94a3b8';
        }
        if (ruleLetter) {
            ruleLetter.innerHTML = hasLetter ? '<i class="fa-solid fa-circle-check" style="color:#10b981;"></i> At least one letter (a-z)' : '<i class="fa-solid fa-circle-xmark" style="color:#ef4444;"></i> At least one letter (a-z)';
            ruleLetter.style.color = hasLetter ? '#047857' : '#94a3b8';
        }
        if (ruleDigit) {
            ruleDigit.innerHTML = hasDigit ? '<i class="fa-solid fa-circle-check" style="color:#10b981;"></i> At least one digit (0-9)' : '<i class="fa-solid fa-circle-xmark" style="color:#ef4444;"></i> At least one digit (0-9)';
            ruleDigit.style.color = hasDigit ? '#047857' : '#94a3b8';
        }
        if (ruleSpecial) {
            ruleSpecial.innerHTML = hasSpecial ? '<i class="fa-solid fa-circle-check" style="color:#10b981;"></i> Special char (!@#$%^&*)' : '<i class="fa-solid fa-circle-xmark" style="color:#ef4444;"></i> Special char (!@#$%^&*)';
            ruleSpecial.style.color = hasSpecial ? '#047857' : '#94a3b8';
        }

        return hasLength && hasLetter && hasDigit && hasSpecial;
    }

    if (pwInput) {
        pwInput.addEventListener('input', function() {
            checkPasswordComplexity(pwInput.value);
        });
    }

    // ---------------------------------------------------------
    // STEP 3: FINAL REGISTRATION & PROFILE SUBMISSION
    // ---------------------------------------------------------
    const finalForm = document.getElementById('final-register-form');
    if (finalForm) {
        finalForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            clearMsg('step3-alert');

            const name = document.getElementById('reg-name').value.trim();
            const password = document.getElementById('reg-password').value;
            const phone = document.getElementById('reg-phone') ? document.getElementById('reg-phone').value.trim() : '';

            if (!name || !password) {
                showMsg('step3-alert', 'Name and password are required.', true);
                return;
            }

            if (!checkPasswordComplexity(password)) {
                showMsg('step3-alert', 'Password does not meet all rules: Must be at least 8 characters and contain at least one letter, one digit, and one special character (!@#$%^&*).', true);
                return;
            }

            const payload = {
                name: name,
                email: regState.email,
                password: password,
                phone: phone,
                role: userRole,
                email_verified: regState.emailVerified,
                aadhaar_verified: regState.aadhaarVerified,
                masked_aadhaar: regState.maskedAadhaar
            };

            // If Tenant, add lifestyle preferences
            if (userRole === 'tenant') {
                payload.tenant_type = document.getElementById('tenant_type') ? document.getElementById('tenant_type').value : 'bachelor';
                payload.has_pets = document.getElementById('has_pets') ? (document.getElementById('has_pets').checked ? 1 : 0) : 0;
                payload.pet_details = document.getElementById('pet_details') ? document.getElementById('pet_details').value.trim() : '';
                payload.diet_pref = document.getElementById('diet_pref') ? document.getElementById('diet_pref').value : 'no_preference';
                payload.smoking_drinking = document.getElementById('smoking_drinking') ? (document.getElementById('smoking_drinking').checked ? 1 : 0) : 0;
                payload.occupation = document.getElementById('occupation') ? document.getElementById('occupation').value.trim() : '';
            }

            const btnSubmit = document.getElementById('btn-submit-registration');
            btnSubmit.disabled = true;
            btnSubmit.innerHTML = 'Creating Account...';

            try {
                const res = await fetch('/api/auth/register-user', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();

                if (data.success) {
                    showMsg('step3-alert', 'Account created and verified! Redirecting to your dashboard...', false);
                    setTimeout(() => {
                        window.location.href = data.redirect_url;
                    }, 1000);
                } else {
                    showMsg('step3-alert', data.error || 'Failed to create account.', true);
                    btnSubmit.disabled = false;
                    btnSubmit.innerHTML = 'Complete Registration';
                }
            } catch (err) {
                showMsg('step3-alert', 'Network error during account registration.', true);
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = 'Complete Registration';
            }
        });
    }
});
