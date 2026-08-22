document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('ask-form');
    const input = document.getElementById('question');
    const btn = document.getElementById('submit-btn');
    const status = document.getElementById('status');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const question = input.value.trim();
        if (!question) return;

        btn.disabled = true;
        input.disabled = true;
        status.textContent = 'שולח...';

        try {
            const formData = new FormData();
            formData.append('question', question);

            const res = await fetch('/api/ask', {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'שגיאה בשליחה');
            }

            const data = await res.json();
            status.textContent = 'מעביר לצ׳אט...';
            window.location.href = data.redirect;
        } catch (err) {
            console.error(err);
            status.textContent = 'שגיאה: ' + (err.message || 'נסה שוב');
            btn.disabled = false;
            input.disabled = false;
        }
    });
});
