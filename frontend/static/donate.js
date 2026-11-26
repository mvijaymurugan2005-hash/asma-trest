/* =====================================================================
   DONATE PAGE SCRIPT
   1. Live validation of every field (errors show while the donor types)
   2. Mobile box with country flag + dial code (intl-tel-input library)
   3. Step 1: send the form to the server  (/api/donate)
   4. Step 2: Online payment (Razorpay) -> the server verifies it, then the receipt is generated
   The values used here (csrf token, trust name ...) come from window.DONATE,
   which is written by donate.html.
   ===================================================================== */
(function () {
  'use strict';

  var CFG = window.DONATE;                       // settings written by donate.html
  var $ = function (id) { return document.getElementById(id); };
  var form = $('df');                            // the donor details form
  var formMsg = $('m');                          // red message above the buttons
  var ref = '';                                  // reference number of this donation (set by the server)

  /* ---------- small helper: POST json and read json back ---------- */
  function post(url, data) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': CFG.csrf },
      body: JSON.stringify(data)
    }).then(function (r) { return r.json(); });
  }

  /* =====================================================================
     1. LIVE VALIDATION
     Every rule returns '' when the value is fine, or the error text to show.
     ===================================================================== */

  /* Typing mistakes we can recognise in e-mail domains: wrong -> right */
  var DOMAIN_FIX = {
    'gmial.com': 'gmail.com', 'gmal.com': 'gmail.com', 'gamil.com': 'gmail.com', 'gnail.com': 'gmail.com',
    'gmail.con': 'gmail.com', 'gmail.co': 'gmail.com', 'gmail.cm': 'gmail.com', 'gmail.in': 'gmail.com',
    'yaho.com': 'yahoo.com', 'yahho.com': 'yahoo.com', 'yahoo.con': 'yahoo.com',
    'hotmial.com': 'hotmail.com', 'hotmail.con': 'hotmail.com', 'outlok.com': 'outlook.com', 'outlook.con': 'outlook.com'
  };

  var rules = {
    name: function (v) {
      v = v.trim().replace(/\s+/g, ' ');
      if (!v) return 'Please enter your full name.';
      if (v.length < 2) return 'Name is too short.';
      if (!/^[\p{L}\p{M}][\p{L}\p{M} .'-]*$/u.test(v)) return 'Name can contain only letters, spaces and . \' -';
      return '';
    },

    email: function (v) {
      v = v.trim().toLowerCase();
      if (!v) return 'Please enter your email address.';
      if (!/^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$/.test(v)) return 'Enter a valid email address, e.g. name@gmail.com';
      var domain = v.split('@')[1];
      if (DOMAIN_FIX[domain]) return 'Did you mean ' + v.split('@')[0] + '@' + DOMAIN_FIX[domain] + ' ?';
      return '';
    },

    address: function (v) {
      v = v.trim().replace(/\s+/g, ' ');
      if (!v) return 'Please enter your full address.';
      if (v.length < 10) return 'Address is too short (' + v.length + '/10 characters). Add street, city, state and PIN code.';
      return '';
    },

    pan: function (v) {
      v = v.trim().toUpperCase();
      var amount = parseInt(form.elements.amount.value, 10) || 0;
      if (!v) return (CFG.panFrom && amount >= CFG.panFrom) ? 'PAN is required for donations of Rs. ' + CFG.panFrom.toLocaleString('en-IN') + ' or more.' : '';
      if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(v)) return 'PAN must look like ABCDE1234F (5 letters, 4 digits, 1 letter).';
      return '';
    },

    amount: function (v) {
      if (v === '') return 'Please enter the donation amount.';
      var n = Number(v);
      if (!Number.isInteger(n)) return 'Enter a whole number of rupees.';
      if (n < 99) return 'Minimum donation is Rs. 99.';
      if (n > 500000) return 'Maximum donation is Rs. 5,00,000.';
      return '';
    }
  };

  /* Show / clear the message under a field */
  function show(field, error, okText) {
    var input = field === 'mobile' ? $('mobile') : form.elements[field];
    var box = $('msg_' + field);
    input.classList.toggle('bad', !!error);
    input.classList.toggle('good', !error && !!input.value.trim());
    box.className = 'fmsg ' + (error ? 'bad' : (input.value.trim() ? 'good' : ''));
    box.textContent = error ? '✖ ' + error : (input.value.trim() && okText ? '✔ ' + okText : '');
    input.setAttribute('aria-invalid', error ? 'true' : 'false');
    return error;
  }

  /* Check one field and show the result */
  function check(field) {
    if (field === 'mobile') return checkMobile();
    var input = form.elements[field];
    return show(field, rules[field](input.value), field === 'email' ? 'Email looks good' : '');
  }

  /* Clear error state on a field while the user is typing */
  function clearField(field) {
    var input = field === 'mobile' ? $('mobile') : form.elements[field];
    var box = $('msg_' + field);
    if (!input || !box) return;
    input.classList.remove('bad', 'good');
    box.className = 'fmsg';
    box.textContent = '';
    input.setAttribute('aria-invalid', 'false');
  }

  /* Do NOT show red errors while typing; clear any previous error as the user edits.
     Full validation runs cleanly when the donor clicks "Donate Now". */
  var touched = {};
  function live(field) {
    var input = field === 'mobile' ? $('mobile') : form.elements[field];
    input.addEventListener('input', function () {
      clearField(field);
      formMsg.textContent = '';
    });
  }
  ['name', 'email', 'address', 'amount'].forEach(live);
  if (form.elements.pan) {
    live('pan');
    form.elements.pan.addEventListener('input', function () { this.value = this.value.toUpperCase(); });
  }

  /* Full name: allow ONLY letters/text (and spaces, dot, apostrophe, hyphen) – block numbers & symbols */
  form.elements.name.addEventListener('input', function () {
    var cleaned = this.value.replace(/[^\p{L}\p{M} .'-]/gu, '');
    if (cleaned !== this.value) this.value = cleaned;
  });

  /* Donation amount: minimum Rs. 99 – can increase, never decrease below 99 */
  var amtInput = form.elements.amount;
  amtInput.addEventListener('keydown', function (e) {
    if (e.key === '-' || e.key === '+' || e.key === 'e' || e.key === 'E' || e.key === '.') {
      e.preventDefault();
    }
    if (e.key === 'ArrowDown' && (parseInt(this.value, 10) || 0) <= 99) {
      e.preventDefault();
      this.value = '99';
    }
  });
  amtInput.addEventListener('input', function () {
    var digits = this.value.replace(/\D/g, '');
    if (digits !== this.value) this.value = digits;
  });
  function clampAmount() {
    var n = parseInt(amtInput.value, 10);
    if (!n || n < 99) amtInput.value = '99';
    else if (n > 500000) amtInput.value = '500000';
    else amtInput.value = String(n);
    clearField('amount');
  }
  amtInput.addEventListener('blur', clampAmount);
  amtInput.addEventListener('change', clampAmount);

  /* ---------- "Did you mean ...?" : click the message to fix the e-mail ---------- */
  $('msg_email').addEventListener('click', function () {
    var m = this.textContent.match(/Did you mean (\S+) \?/);
    if (m) { form.elements.email.value = m[1]; check('email'); }
  });

  /* =====================================================================
     2. MOBILE NUMBER WITH COUNTRY FLAG
     ===================================================================== */
  var mobileInput = $('mobile');
  var iti = window.intlTelInput(mobileInput, {
    initialCountry: 'in',          // India is selected first
    separateDialCode: true,        // shows the flag and +91 beside the box
    countrySearch: true,           // donors can type a country name to find it
    strictMode: true,              // blocks letters and too many digits
    countryOrder: ['in', 'ae', 'sa', 'sg', 'my', 'qa', 'kw', 'om', 'us', 'gb', 'au', 'ca'],   // common countries on top
    containerClass: 'itibox'
  });

  var MOBILE_ERR = {
    TOO_SHORT: 'Number is too short for this country.',
    TOO_LONG: 'Number is too long for this country.',
    INVALID_LENGTH: 'Wrong number of digits for this country.',
    INVALID_COUNTRY_CODE: 'Invalid country code.'
  };

  function checkMobile() {
    var typed = mobileInput.value.trim();
    var country = iti.getSelectedCountry() || {};
    if (!typed) return show('mobile', 'Please enter your mobile number.');
    var err = '';
    if (!iti.isValidNumber()) {
      err = MOBILE_ERR[iti.getValidationError()] || 'Enter a valid mobile number for ' + (country.name || 'this country') + '.';
    } else if (country.iso2 === 'in' && !/^[6-9]\d{9}$/.test(iti.getNumber().slice(3))) {
      err = 'Indian mobile numbers are 10 digits and start with 6, 7, 8 or 9.';
    }
    return show('mobile', err, 'Valid number: ' + iti.getNumber());
  }
  mobileInput.addEventListener('countrychange', function () { clearField('mobile'); });
  live('mobile');

  /* =====================================================================
     3. STEP 1 - SEND THE FORM  (button #bo)
     ===================================================================== */
  form.onsubmit = function (e) {
    e.preventDefault();
    formMsg.textContent = '';

    /* validate everything; show every error; jump to the first wrong field */
    var firstBad = '';
    var fields = ['name', 'mobile', 'email', 'address', 'amount'];
    if (form.elements.pan) fields.splice(4, 0, 'pan');
    fields.forEach(function (f) {
      touched[f] = true;
      if (check(f) && !firstBad) firstBad = f;
    });
    if (firstBad) {
      (firstBad === 'mobile' ? mobileInput : form.elements[firstBad]).focus();
      formMsg.textContent = 'Please correct the fields marked in red.';
      return;
    }

    var body = Object.fromEntries(new FormData(form));
    body.mobile = iti.getNumber();            // full number with country code, e.g. +919876543210
    setBusy(true);

    post('/api/donate', body).then(function (j) {
      if (!j.ok) { formMsg.textContent = j.error; setBusy(false); return; }
      ref = j.ref;
      startOnlinePayment(j);
    }).catch(function () {
      formMsg.textContent = 'Network error. Please try again.';
      setBusy(false);
    });
  };

  function setBusy(on) {
    if ($('bo')) $('bo').disabled = on;
  }

  /* =====================================================================
     4. ONLINE PAYMENT (Razorpay) - the receipt is made automatically
     ===================================================================== */
  function loadRazorpay() {                    // load Razorpay's checkout script only when needed
    return new Promise(function (resolve, reject) {
      if (window.Razorpay) return resolve();
      var s = document.createElement('script');
      s.src = 'https://checkout.razorpay.com/v1/checkout.js';
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function startOnlinePayment(j) {
    loadRazorpay().then(function () {
      var box = new window.Razorpay({
        key: j.key,
        order_id: j.order_id,
        amount: j.amount * 100,
        currency: 'INR',
        name: CFG.trustName,
        description: 'Donation ' + j.ref,
        prefill: { name: j.name, email: j.email, contact: j.mobile },
        theme: { color: '#0b3a8c' },
        /* payment finished -> the server checks the signature, then makes the receipt */
        handler: function (r) {
          formMsg.textContent = '';
          $('wait').hidden = false;            // "Payment received - preparing your certificate..."
          post('/api/verify', {
            ref: j.ref,
            razorpay_payment_id: r.razorpay_payment_id,
            razorpay_order_id: r.razorpay_order_id,
            razorpay_signature: r.razorpay_signature
          }).then(function (v) {
            if (v.ok) location = v.url;       // receipt page: certificate + Download button
            else { $('wait').hidden = true; formMsg.textContent = 'Payment could not be verified. If money was deducted, contact the Trust with reference ' + j.ref; setBusy(false); }
          }).catch(function () { location = '/receipt/' + j.ref; });
        },
        modal: {                               // donor closed the payment window
          ondismiss: function () {
            post('/api/fail', { ref: j.ref });
            formMsg.textContent = 'Payment was cancelled. You can try again.';
            setBusy(false);
          }
        }
      });
      box.on('payment.failed', function () {
        post('/api/fail', { ref: j.ref });
        formMsg.textContent = 'Payment failed. No money was taken. Please try again.';
        setBusy(false);
      });
      box.open();
    }).catch(function () {
      formMsg.textContent = 'Could not load the online payment window. Check your internet and try again.';
      setBusy(false);
    });
  }

})();
