// לוגיקת הדף: בדיקת התחברות, שליחת הקישור, והצגת התקדמות חיה.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const views = ["view-signin", "view-form", "view-progress", "view-done"];

  // מציג מצב אחד בלבד מתוך הארבעה
  function show(viewId) {
    views.forEach((id) => { $(id).hidden = id !== viewId; });
  }

  function showError(message) {
    $("error").textContent = message;
    $("error").hidden = !message;
  }

  // ---------- התחברות ----------

  const AUTH_MESSAGES = {
    cancelled: "ההתחברות בוטלה.",
    failed: "ההתחברות נכשלה. נסה שוב.",
    scope: "כדי להעלות קבצים צריך לאשר את ההרשאה לדרייב במסך של גוגל.",
  };

  async function loadSession() {
    // אם חזרנו מגוגל עם שגיאה, היא מופיעה בכתובת (‎?auth=...)
    const params = new URLSearchParams(location.search);
    const authResult = params.get("auth");
    if (authResult) history.replaceState(null, "", location.pathname);

    let data = { authenticated: false };
    try {
      data = await (await fetch("/api/me", { credentials: "same-origin" })).json();
    } catch {
      showError("אין חיבור לשרת. רענן את הדף ונסה שוב.");
    }

    if (data.authenticated) {
      $("user-name").textContent = data.user.name || "";
      $("user-name").title = data.user.email || "";
      if (data.user.picture) {
        $("avatar").src = data.user.picture;
        $("avatar").referrerPolicy = "no-referrer";
        $("avatar").hidden = false;
      }
      $("account").hidden = false;
      show("view-form");
      $("album-url").focus({ preventScroll: true });
    } else {
      $("account").hidden = true;
      show("view-signin");
    }
    if (authResult && AUTH_MESSAGES[authResult]) showError(AUTH_MESSAGES[authResult]);
  }

  $("signin").addEventListener("click", () => { location.href = "/auth/login"; });

  $("logout").addEventListener("click", async () => {
    try { await fetch("/auth/logout", { method: "POST", credentials: "same-origin" }); } catch { /* ממשיכים בכל מקרה */ }
    location.href = "/";
  });

  // ---------- העלאה ----------

  // בדיקה מהירה בצד הלקוח; השרת בודק שוב בעצמו
  function looksLikeAlbumLink(value) {
    return /icloud\.com\/sharedalbum\/.*#[A-Za-z0-9]{8,}/.test(value) || /^[A-Za-z0-9]{8,64}$/.test(value);
  }

  function setProgress(done, total) {
    const bar = $("bar");
    if (!total) {
      bar.classList.add("indeterminate");
      bar.removeAttribute("aria-valuenow");
      return;
    }
    const percent = Math.round((done / total) * 100);
    bar.classList.remove("indeterminate");
    bar.setAttribute("aria-valuenow", String(percent));
    $("bar-fill").style.width = percent + "%";
  }

  function handleEvent(event, state) {
    switch (event.type) {
      case "album":
        state.total = event.total;
        $("progress-title").textContent = `מעתיק את "${event.name}"`;
        $("progress-detail").textContent = `0 מתוך ${event.total} קבצים`;
        setProgress(0, event.total);
        break;
      case "progress": {
        const handled = event.done + event.failed;
        $("progress-detail").textContent = `${handled} מתוך ${event.total} קבצים`;
        setProgress(handled, event.total);
        break;
      }
      case "done":
        state.finished = true;
        showDone(event);
        break;
      case "error":
        state.finished = true;
        show("view-form");
        showError(event.message + (event.folder_url ? " חלק מהקבצים כבר הועלו לתיקייה בדרייב." : ""));
        break;
      // "ping" – אות חיים מהשרת, אין מה להציג
    }
  }

  function showDone(event) {
    $("done-title").textContent = "האלבום בדרייב שלך";
    $("done-detail").textContent =
      `${event.uploaded} מתוך ${event.total} קבצים הועלו לתיקייה "${event.folder_name}"`;
    $("folder-link").textContent = event.folder_url.replace(/^https:\/\//, "");
    $("folder-link").href = event.folder_url;
    $("open-folder").href = event.folder_url;

    const failedList = $("failed-list");
    failedList.replaceChildren();
    $("failed-box").hidden = event.failed.length === 0;
    if (event.failed.length) {
      $("failed-summary").textContent = `${event.failed.length} קבצים לא הועלו`;
      event.failed.forEach((name) => {
        const item = document.createElement("li");
        item.textContent = name;
        failedList.append(item);
      });
    }
    show("view-done");
  }

  $("view-form").addEventListener("submit", async (submitEvent) => {
    submitEvent.preventDefault();
    showError("");

    const input = $("album-url");
    const url = input.value.trim();
    if (!looksLikeAlbumLink(url)) {
      input.classList.add("invalid");
      showError(url ? "זה לא נראה כמו קישור של אלבום משותף מ-iCloud." : "הדבק קישור של אלבום משותף.");
      input.focus();
      return;
    }

    $("progress-title").textContent = "מאתר את האלבום…";
    $("progress-detail").textContent = "זה יכול לקחת כמה דקות באלבומים גדולים. אפשר להשאיר את הדף פתוח.";
    $("bar-fill").style.width = "";
    setProgress(0, 0);
    show("view-progress");

    const state = { total: 0, finished: false };
    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        if (response.status === 401) { await loadSession(); }
        else { show("view-form"); }
        showError(data.error || "משהו השתבש. נסה שוב.");
        return;
      }

      // התשובה היא זרם של שורות JSON; קוראים אותה תוך כדי שהיא מגיעה
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        lines.filter(Boolean).forEach((line) => handleEvent(JSON.parse(line), state));
      }
      if (!state.finished) throw new Error("stream ended early");
    } catch {
      show("view-form");
      showError("החיבור לשרת נקטע באמצע. בדוק בדרייב מה כבר הועלה, ונסה שוב.");
    }
  });

  $("album-url").addEventListener("input", () => {
    $("album-url").classList.remove("invalid");
    showError("");
  });

  // Enter שולח את הטופס (אין צורך בירידת שורה בשדה של קישור)
  $("album-url").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("view-form").requestSubmit();
    }
  });

  // ---------- סיום ----------

  $("copy").addEventListener("click", async () => {
    const link = $("folder-link").href;
    try {
      await navigator.clipboard.writeText(link);
    } catch {
      // דפדפנים ישנים / הקשר לא מאובטח
      const helper = document.createElement("textarea");
      helper.value = link;
      document.body.append(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
    const button = $("copy");
    button.textContent = "הועתק ✓";
    button.classList.add("copied");
    setTimeout(() => { button.textContent = "העתק קישור"; button.classList.remove("copied"); }, 2000);
  });

  $("again").addEventListener("click", () => {
    $("album-url").value = "";
    showError("");
    show("view-form");
    $("album-url").focus();
  });

  loadSession();
})();
