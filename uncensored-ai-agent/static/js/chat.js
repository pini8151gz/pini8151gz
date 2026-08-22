(function () {
    const messagesEl = document.getElementById('messages');
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const statusEl = document.getElementById('connection-status');
    const typingEl = document.getElementById('typing');

    let ws = null;
    let reconnectAttempts = 0;
    let keepAlive = null;
    const maxReconnect = 20;
    // הודעות ששלחנו בעצמנו וכבר הוצגו אופטימית – כדי לא להציג אותן פעמיים מה-WebSocket
    const pendingEchoes = [];

    function formatTime(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            return d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
        } catch {
            return iso.slice(11, 16) || '';
        }
    }

    function addMessage(role, content, createdAt) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        div.innerHTML = `
            <div class="bubble">
                <div class="content"></div>
                <div class="time">${formatTime(createdAt)}</div>
            </div>
        `;
        div.querySelector('.content').textContent = content;
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function setStatus(text, online = false) {
        statusEl.textContent = text;
        statusEl.classList.toggle('online', online);
    }

    function connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${protocol}//${location.host}/ws/${SESSION_ID}`);

        ws.onopen = () => {
            reconnectAttempts = 0;
            setStatus('מחובר', true);
            // Keep alive
            clearInterval(keepAlive);
            keepAlive = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send('ping');
                }
            }, 25000);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                if (data.type === 'history') {
                    // Already rendered from server, but can sync if needed
                    return;
                }

                if (data.type === 'new_message') {
                    // Avoid duplicate if we just sent it ourselves
                    if (data.role === 'user') {
                        const i = pendingEchoes.indexOf(data.content);
                        if (i !== -1) {
                            pendingEchoes.splice(i, 1);
                            return;
                        }
                    }
                    addMessage(data.role, data.content, data.created_at);

                    if (data.role === 'assistant') {
                        typingEl.style.display = 'none';
                    }
                }
            } catch (e) {
                console.log('WS message:', event.data);
            }
        };

        ws.onclose = () => {
            clearInterval(keepAlive);
            setStatus('מתנתק... מנסה שוב', false);
            if (reconnectAttempts < maxReconnect) {
                reconnectAttempts++;
                setTimeout(connect, Math.min(1000 * reconnectAttempts, 8000));
            } else {
                setStatus('אין חיבור', false);
            }
        };

        ws.onerror = () => {
            setStatus('שגיאת חיבור', false);
        };
    }

    // Send follow-up message
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;

        input.value = '';
        sendBtn.disabled = true;

        // Optimistic UI
        pendingEchoes.push(text);
        addMessage('user', text, new Date().toISOString());
        typingEl.style.display = 'flex';

        try {
            const formData = new FormData();
            formData.append('message', text);

            const res = await fetch(`/api/chat/${SESSION_ID}/message`, {
                method: 'POST',
                body: formData
            });

            if (!res.ok) throw new Error('שליחה נכשלה');
        } catch (err) {
            console.error(err);
            typingEl.style.display = 'none';
        } finally {
            sendBtn.disabled = false;
            input.focus();
        }
    });

    // Start
    connect();
    input.focus();

    // Auto scroll on load
    messagesEl.scrollTop = messagesEl.scrollHeight;
})();
