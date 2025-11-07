
document.addEventListener('DOMContentLoaded', () => {
  console.log('script loaded');
  const messages = document.getElementById('messages');
  const input = document.getElementById('msg');
  const sendBtn = document.getElementById('sendBtn');
  const imageInput = document.getElementById('imageInput');
  const voiceBtn = document.getElementById('voiceBtn');

  // Voice recognition variables
  let recognition = null;
  let isListening = false;

  // Initialize voice recognition if available
  if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      input.value = transcript;
      updateVoiceButton(false);
    };

    recognition.onerror = (event) => {
      console.error('Speech recognition error:', event.error);
      updateVoiceButton(false);
      addMessage('system', `Voice input error: ${event.error}`);
    };

    recognition.onend = () => {
      updateVoiceButton(false);
    };
  } else {
    console.warn('Speech recognition not supported in this browser');
    if (voiceBtn) voiceBtn.style.display = 'none';
  }

  function updateVoiceButton(listening) {
    isListening = listening;
    if (voiceBtn) {
      voiceBtn.textContent = listening ? '🎤 Listening...' : '🎤 Voice';
      voiceBtn.style.background = listening ? '#ff4444' : '';
    }
  }

  function toggleVoiceInput() {
    if (!recognition) {
      addMessage('system', 'Voice input is not supported in your browser');
      return;
    }

    if (isListening) {
      recognition.stop();
      updateVoiceButton(false);
    } else {
      try {
        recognition.start();
        updateVoiceButton(true);
      } catch (error) {
        console.error('Error starting voice recognition:', error);
      }
    }
  }

  function addMessage(who, text, imageData = null) {
    const el = document.createElement('div');
    el.className = 'message ' + who;

    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    // Add image if provided
    if (imageData) {
      const imgContainer = document.createElement('div');
      imgContainer.className = 'image-container';

      const img = document.createElement('img');
      img.src = imageData;
      img.alt = 'Uploaded image';
      img.className = 'chat-image';

      imgContainer.appendChild(img);
      bubble.appendChild(imgContainer);

      // Add some space between image and text
      if (text) {
        const textSpacer = document.createElement('div');
        textSpacer.style.marginTop = '10px';
        bubble.appendChild(textSpacer);
      }
    }

    // Add text if provided
    if (text) {
      const textElement = document.createElement('div');
      textElement.className = 'message-text';

      // Convert markdown-style formatting to HTML
      const formattedText = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');

      textElement.innerHTML = formattedText;
      bubble.appendChild(textElement);
    }

    el.appendChild(bubble);
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
  }

  function handleImageUpload(file) {
    return new Promise((resolve, reject) => {
      if (!file.type.startsWith('image/')) {
        reject(new Error('Please select an image file'));
        return;
      }

      // Check file size (max 5MB)
      if (file.size > 5 * 1024 * 1024) {
        reject(new Error('Image size should be less than 5MB'));
        return;
      }

      const reader = new FileReader();
      reader.onload = (e) => {
        resolve(e.target.result);
      };
      reader.onerror = () => {
        reject(new Error('Failed to read image file'));
      };
      reader.readAsDataURL(file);
    });
  }

  async function analyzeImage(imageFile, textMessage = '') {
    try {
      const formData = new FormData();
      formData.append('image', imageFile);
      if (textMessage) {
        formData.append('message', textMessage);
      }

      console.log('Sending image analysis request...');

      const res = await fetch('/api/analyze-image', {
        method: 'POST',
        body: formData
      });

      const responseText = await res.text();

      // Check if we got HTML (login page)
      if (responseText.trim().startsWith('<!DOCTYPE') || responseText.includes('<html>') || responseText.includes('login')) {
        throw new Error('Authentication required. Please log in to use image analysis.');
      }

      if (!res.ok) {
        let errorData;
        try {
          errorData = JSON.parse(responseText);
          throw new Error(errorData.error || `Server error: ${res.status}`);
        } catch (e) {
          throw new Error(`Server error: ${res.status}. Please try again.`);
        }
      }

      // Parse successful JSON response
      const data = JSON.parse(responseText);
      return data;

    } catch (error) {
      console.error('Image analysis error:', error);
      throw error;
    }
  }

  async function sendMessage() {
    const msg = input.value.trim();
    const imageFile = imageInput?.files[0];

    if (!msg && !imageFile) return;

    sendBtn.disabled = true;

    try {
      // Handle image upload and analysis
      if (imageFile) {
        addMessage('system', 'Uploading and analyzing image...');

        // First, read the image for display
        const imageData = await handleImageUpload(imageFile);

        // Show user message with image
        const displayMessage = msg || `I uploaded this image for analysis`;
        addMessage('user', displayMessage, imageData);

        // Analyze the image
        try {
          const analysisResult = await analyzeImage(imageFile, msg);

          if (analysisResult.success) {
            addMessage('bot', analysisResult.response);
          } else {
            addMessage('bot', `Analysis completed with issues: ${analysisResult.error}`);
          }
        } catch (analysisError) {
          if (analysisError.message.includes('Authentication required') || analysisError.message.includes('login')) {
            addMessage('bot', '🔒 Please log in to use the image analysis feature. You can still chat without images.');
          } else {
            addMessage('bot', `Image analysis failed: ${analysisError.message}`);
          }
        }

        // Clear image input
        imageInput.value = '';
      }
      // Handle text message only
      else if (msg) {
        addMessage('user', msg);

        // Send to chat API
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({message: msg})
        });

        if (!res.ok) throw new Error('Network response not ok');
        const data = await res.json();
        addMessage('bot', data.response || 'No response');
      }

    } catch (err) {
      console.error('Send message error:', err);
      addMessage('bot', `Error: ${err.message}`);
    } finally {
      sendBtn.disabled = false;
      input.value = '';
      input.focus();
    }
  }

  // Event listeners
  sendBtn && sendBtn.addEventListener('click', sendMessage);
  voiceBtn && voiceBtn.addEventListener('click', toggleVoiceInput);

  input && input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Image input change handler
  imageInput && imageInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      const file = e.target.files[0];

      // Validate file type
      if (!file.type.startsWith('image/')) {
        addMessage('system', 'Please select a valid image file (JPEG, PNG, GIF, WebP)');
        imageInput.value = '';
        return;
      }

      // Validate file size
      if (file.size > 5 * 1024 * 1024) {
        addMessage('system', 'Image size must be less than 5MB');
        imageInput.value = '';
        return;
      }

      console.log('Image selected:', file.name, file.type, file.size);

      // Auto-send the image
      sendMessage();
    }
  });
});