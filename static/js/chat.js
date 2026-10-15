// Real-Time In-App Chat Poller and Sender

document.addEventListener('DOMContentLoaded', function () {
    const chatContainer = document.getElementById('chat-window-box');
    if (!chatContainer) return; // Not on chat page

    const chatId = chatContainer.getAttribute('data-chat-id');
    const messagesList = document.getElementById('chat-messages-container');
    const messageInput = document.getElementById('chat-input-text');
    const sendButton = document.getElementById('chat-send-btn');
    const chatForm = document.getElementById('chat-form');

    let lastKnownMessageCount = 0;
    let isFetching = false;

    function scrollToBottom() {
        if (messagesList) {
            messagesList.scrollTop = messagesList.scrollHeight;
        }
    }

    function renderMessage(msg) {
        const bubble = document.createElement('div');
        bubble.className = msg.is_mine ? 'message-bubble message-outgoing' : 'message-bubble message-incoming';
        
        let headerHtml = '';
        if (!msg.is_mine) {
            headerHtml = `<div style="font-weight: 700; font-size: 0.75rem; margin-bottom: 3px; color: #475569;">${msg.sender_name}</div>`;
        }

        const readStatus = msg.is_mine ? (msg.is_read ? ' ✓✓' : ' ✓') : '';

        bubble.innerHTML = `
            ${headerHtml}
            <div style="word-break: break-word;">${escapeHtml(msg.message_text)}</div>
            <span class="message-time">${msg.created_at ? msg.created_at.split(' ')[1] || msg.created_at : ''}${readStatus}</span>
        `;
        return bubble;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.innerText = text;
        return div.innerHTML;
    }

    async function fetchMessages(forceScroll = false) {
        if (isFetching) return;
        isFetching = true;

        try {
            const res = await fetch(`/api/chat/${chatId}/messages`);
            const data = await res.json();

            if (data.success && data.messages) {
                if (data.messages.length !== lastKnownMessageCount) {
                    messagesList.innerHTML = '';
                    data.messages.forEach(msg => {
                        messagesList.appendChild(renderMessage(msg));
                    });
                    lastKnownMessageCount = data.messages.length;
                    scrollToBottom();
                } else if (forceScroll) {
                    scrollToBottom();
                }
            }
        } catch (e) {
            console.error('Chat poll error:', e);
        } finally {
            isFetching = false;
        }
    }

    // Send Message
    async function sendMessage() {
        const text = messageInput.value.trim();
        if (!text) return;

        messageInput.value = '';
        messageInput.disabled = true;
        sendButton.disabled = true;

        try {
            const res = await fetch(`/api/chat/${chatId}/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });
            const data = await res.json();

            if (data.success) {
                // Immediate refresh
                await fetchMessages(true);
            }
        } catch (e) {
            console.error('Failed to send message:', e);
        } finally {
            messageInput.disabled = false;
            sendButton.disabled = false;
            messageInput.focus();
        }
    }

    if (chatForm) {
        chatForm.addEventListener('submit', function (e) {
            e.preventDefault();
            sendMessage();
        });
    }

    // Initial load
    fetchMessages(true);

    // Auto-poll every 2.5 seconds
    const interval = setInterval(fetchMessages, 2500);

    window.addEventListener('beforeunload', () => {
        clearInterval(interval);
    });
});
