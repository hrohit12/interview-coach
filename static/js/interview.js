/**
 * interview.js — AI Interview Coach
 * Real-time voice pipeline:
 *   WS /ws-interview ↔ edge-tts audio + faster-whisper STT + VAD
 *   MediaPipe Face Detection for anti-cheat monitoring
 */

// ─── Session ──────────────────────────────────────────────────────────────────
const IC = {
    sessionId: sessionStorage.getItem('ic_session_id'),
    apiType: sessionStorage.getItem('ic_api_type'),
    apiKey: sessionStorage.getItem('ic_api_key'),
    model: sessionStorage.getItem('ic_model'),
    name: sessionStorage.getItem('ic_name'),
    qualification: sessionStorage.getItem('ic_qualification'),
    topic: sessionStorage.getItem('ic_topic'),
    difficulty: sessionStorage.getItem('ic_difficulty'),
    voice: sessionStorage.getItem('ic_voice') || 'en-US-JennyNeural',

    // State flags
    isSpeaking: false,
    isRecording: false,
    micMuted: false,
    cameraOn: true,
    vadActive: false,

    // Streams / resources
    cameraStream: null,
    micStream: null,
    audioCtx: null,
    analyser: null,
    mediaRecorder: null,
    audioChunks: [],
    silenceTimer: null,
    vadRaf: null,
    ws: null,
    timerInterval: null,
    elapsedSecs: 0,

    // VAD config
    VOICE_THRESH: 10,
    SILENCE_MS: 2000,
};

if (!IC.sessionId || !IC.apiKey || !IC.name) window.location.href = '/';

// ─── DOM helpers ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const qs = sel => document.querySelector(sel);
const waveBars = document.querySelectorAll('.wave-bar');

// ─── Timer ────────────────────────────────────────────────────────────────────
function startTimer() {
    IC.timerInterval = setInterval(() => {
        IC.elapsedSecs++;
        const s = formatTime(IC.elapsedSecs);
        $('timerDisplay').textContent = s;
        $('timeShared').textContent = s;
        $('timeFooter').textContent = s;
    }, 1000);
}

// ─── Webcam (WebRTC) ──────────────────────────────────────────────────────────
async function setupWebcam() {
    try {
        IC.cameraStream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
            audio: false,
        });
        const vid = $('webcamVideo');
        vid.srcObject = IC.cameraStream;
        vid.style.display = 'block';
        $('noCamOverlay').classList.add('hidden');
        // Start face detection after stream is ready
        vid.onloadedmetadata = () => initFaceDetection(vid);
    } catch {
        $('webcamVideo').style.display = 'none';
        $('noCamOverlay').classList.remove('hidden');
    }
}

function toggleCamera() {
    if (!IC.cameraStream) return;
    IC.cameraOn = !IC.cameraOn;
    IC.cameraStream.getVideoTracks().forEach(t => t.enabled = IC.cameraOn);
    $('webcamVideo').style.opacity = IC.cameraOn ? '1' : '0';
}

function toggleMicMute() {
    IC.micMuted = !IC.micMuted;
    if (IC.micStream) IC.micStream.getAudioTracks().forEach(t => t.enabled = !IC.micMuted);
    $('micDot').classList.toggle('bg-emerald-400', !IC.micMuted);
    $('micDot').classList.toggle('bg-red-500', IC.micMuted);
    $('micIcon').style.opacity = IC.micMuted ? '0.35' : '1';
}

// ─── Face Detection (MediaPipe) ───────────────────────────────────────────────
let _faceDetector = null;
let _faceMissedSecs = 0;
let _faceCheckInterval = null;

function initFaceDetection(videoEl) {
    if (typeof FaceDetection === 'undefined') return; // CDN not loaded

    _faceDetector = new FaceDetection({
        locateFile: f => `https://cdn.jsdelivr.net/npm/@mediapipe/face_detection@0.4/${f}`,
    });
    _faceDetector.setOptions({ model: 'short', minDetectionConfidence: 0.5 });
    _faceDetector.onResults(onFaceResults);

    _faceCheckInterval = setInterval(async () => {
        if (videoEl.readyState >= 2 && IC.cameraOn) {
            try { await _faceDetector.send({ image: videoEl }); }
            catch { }
        }
    }, 1500);
}

function onFaceResults(results) {
    const faces = results.detections || [];
    if (faces.length === 0) {
        _faceMissedSecs += 1.5;
        if (_faceMissedSecs >= 3) showFaceWarning('Please keep your face visible.');
    } else if (faces.length > 1) {
        _faceMissedSecs = 0;
        showFaceWarning('Multiple faces detected. Please ensure only you are on screen.');
    } else {
        _faceMissedSecs = 0;
        hideFaceWarning();
    }
}

function showFaceWarning(msg) {
    $('faceWarningText').textContent = msg;
    $('faceWarning').classList.add('show');
}
function hideFaceWarning() {
    $('faceWarning').classList.remove('show');
}

// ─── AI State UI ──────────────────────────────────────────────────────────────
const AI_STATES = {
    thinking: { badge: 'yellow', label: 'Thinking…', wave: 'idle', orb: 'thinking' },
    speaking: { badge: 'blue', label: 'Coach Speaking', wave: 'speaking', orb: 'speaking' },
    listening: { badge: 'green', label: 'Listening…', wave: 'idle', orb: '' },
    recording: { badge: 'green', label: 'Recording…', wave: 'speaking', orb: '' },
    transcribing: { badge: 'yellow', label: 'Transcribing…', wave: 'idle', orb: 'thinking' },
    connecting: { badge: 'slate', label: 'Connecting…', wave: 'silent', orb: '' },
};

const BADGE_COLORS = {
    yellow: 'bg-amber-50 text-amber-600 border-amber-200',
    blue: 'bg-blue-50 text-blue-600 border-blue-200',
    green: 'bg-emerald-50 text-emerald-600 border-emerald-200',
    slate: 'bg-slate-100 text-slate-500 border-slate-200',
};

function setAIState(state) {
    const cfg = AI_STATES[state] || AI_STATES.listening;

    // Badge
    const badge = $('aiStatusBadge');
    badge.className = `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide border mb-2 ${BADGE_COLORS[cfg.badge] || BADGE_COLORS.slate}`;
    $('aiStatusText').textContent = cfg.label;

    // Orb
    $('aiOrb').className = `ai-orb ${cfg.orb}`;

    // Waveform
    waveBars.forEach(b => {
        b.className = 'wave-bar';
        if (cfg.wave === 'speaking') b.classList.add('speaking');
        else if (cfg.wave === 'idle') b.classList.add('idle');
        else b.classList.add('silent');
    });

    // Dot + mic ring
    const rec = state === 'recording';
    $('micPulseRing').classList.toggle('hidden', !rec);
    $('micDot').style.background = rec ? '#10B981' : IC.micMuted ? '#EF4444' : '#10B981';
}

// ─── WebSocket ────────────────────────────────────────────────────────────────
function connectWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws-interview`);
    IC.ws = ws;

    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
        $('wsDot').className = 'w-1.5 h-1.5 rounded-full bg-emerald-400 transition-colors';
        ws.send(JSON.stringify({
            type: 'init',
            session_id: IC.sessionId,
            api_type: IC.apiType,
            api_key: IC.apiKey,
            model: IC.model,
            voice: IC.voice,
            name: IC.name,
            qualification: IC.qualification,
            topic: IC.topic,
            difficulty: IC.difficulty,
        }));
    };

    ws.onmessage = async event => {
        const data = JSON.parse(event.data);
        switch (data.type) {

            case 'status':
                setAIState(data.state);
                if (data.state === 'listening') {
                    $('transcriptBox').textContent = 'Speak your answer…';
                    $('transcriptBox').classList.add('text-slate-400', 'italic');
                }
                break;

            case 'question':
                $('currentQuestionEl').textContent = data.text;
                $('questionCounter').textContent = `Q ${data.question_number} / ${data.max_questions}`;
                $('progressBar').style.width = `${(data.question_number / data.max_questions) * 100}%`;
                $('qLabel').textContent = `Question ${data.question_number}`;
                addChat('coach', data.text);
                setAIState('speaking');
                if (data.audio_b64) await playAudio(data.audio_b64);
                setAIState('listening');
                startVAD();
                break;

            case 'transcript':
                $('transcriptBox').textContent = data.text;
                $('transcriptBox').classList.remove('text-slate-400', 'italic');
                addChat('you', data.text);
                break;

            case 'feedback':
                updateInsights(data);
                setAIState('speaking');
                if (data.audio_b64) await playAudio(data.audio_b64);
                break;

            case 'report_ready':
                await finishInterview(true);
                break;

            case 'error':
                showToast('Error: ' + data.message, 'error');
                setAIState('listening');
                break;
        }
    };

    ws.onclose = () => {
        $('wsDot').className = 'w-1.5 h-1.5 rounded-full bg-slate-400 transition-colors';
    };

    ws.onerror = () => showToast('WebSocket connection failed.', 'error');
}

// ─── Audio playback (base64 MP3) ──────────────────────────────────────────────
function playAudio(b64) {
    return new Promise(resolve => {
        try {
            const raw = atob(b64);
            const buf = new Uint8Array(raw.length);
            for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
            const blob = new Blob([buf], { type: 'audio/mpeg' });
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            IC.isSpeaking = true;
            audio.onended = () => { IC.isSpeaking = false; URL.revokeObjectURL(url); resolve(); };
            audio.onerror = () => { IC.isSpeaking = false; URL.revokeObjectURL(url); resolve(); };
            audio.play().catch(resolve);
        } catch { resolve(); }
    });
}

// ─── Web Audio VAD ────────────────────────────────────────────────────────────
async function setupMic() {
    try {
        IC.micStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 16000 }
        });
        IC.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const src = IC.audioCtx.createMediaStreamSource(IC.micStream);
        IC.analyser = IC.audioCtx.createAnalyser();
        IC.analyser.fftSize = 512;
        IC.analyser.smoothingTimeConstant = 0.8;
        src.connect(IC.analyser);
        return true;
    } catch { return false; }
}

function getRMS() {
    if (!IC.analyser) return 0;
    const buf = new Uint8Array(IC.analyser.fftSize);
    IC.analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) { const d = (v - 128) / 128; sum += d * d; }
    return Math.sqrt(sum / buf.length) * 100;
}

function startVAD() {
    if (IC.vadActive || IC.isSpeaking) return;
    IC.vadActive = true;

    function tick() {
        if (!IC.vadActive) return;
        const rms = getRMS();

        // Volume bar
        const pct = Math.min(rms * 4, 100);
        $('volBar').style.width = pct + '%';
        $('volBar').style.opacity = pct > 2 ? '1' : '0';

        // Waveform while recording
        if (IC.isRecording) {
            waveBars.forEach((b, i) => {
                const h = Math.max(8, Math.min(32, rms * 2.2 + Math.sin(Date.now() / 120 + i) * 5));
                b.style.height = h + 'px';
            });
        }

        if (!IC.isRecording && rms > IC.VOICE_THRESH && !IC.micMuted) {
            startRecording();
        } else if (IC.isRecording) {
            if (rms >= IC.VOICE_THRESH) {
                clearTimeout(IC.silenceTimer); IC.silenceTimer = null;
            } else if (!IC.silenceTimer) {
                IC.silenceTimer = setTimeout(() => {
                    if (IC.isRecording) stopRecording();
                }, IC.SILENCE_MS);
            }
        }
        IC.vadRaf = requestAnimationFrame(tick);
    }
    IC.vadRaf = requestAnimationFrame(tick);
}

function stopVAD() {
    IC.vadActive = false;
    if (IC.vadRaf) { cancelAnimationFrame(IC.vadRaf); IC.vadRaf = null; }
    $('volBar').style.opacity = '0';
}

// ─── MediaRecorder ────────────────────────────────────────────────────────────
function _mimeType() {
    return ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
        .find(t => MediaRecorder.isTypeSupported(t)) || '';
}

function startRecording() {
    if (IC.isRecording || !IC.micStream) return;
    const mime = _mimeType();
    IC.audioChunks = [];
    IC.mediaRecorder = new MediaRecorder(IC.micStream, mime ? { mimeType: mime } : {});
    IC.mediaRecorder.ondataavailable = e => {
        if (e.data?.size > 0) {
            IC.audioChunks.push(e.data);
            // Stream chunks live to server (binary)
            if (IC.ws?.readyState === WebSocket.OPEN) {
                e.data.arrayBuffer().then(buf => IC.ws.send(buf));
            }
        }
    };
    IC.mediaRecorder.onstop = () => {
        if (IC.ws?.readyState === WebSocket.OPEN) {
            IC.ws.send(JSON.stringify({ type: 'end_speech' }));
        }
        setAIState('transcribing');
    };
    IC.mediaRecorder.start(200);
    IC.isRecording = true;
    setAIState('recording');
}

function stopRecording() {
    if (!IC.isRecording || !IC.mediaRecorder) return;
    clearTimeout(IC.silenceTimer); IC.silenceTimer = null;
    IC.isRecording = false;
    IC.mediaRecorder.stop();
    stopVAD();
}

// ─── Coaching Panel ───────────────────────────────────────────────────────────
let _strengths = [], _improvements = [];

function updateInsights(ev) {
    (ev.strengths || []).forEach(s => { if (!_strengths.includes(s)) _strengths.push(s); });
    (ev.improvements || []).forEach(s => { if (!_improvements.includes(s)) _improvements.push(s); });

    $('strengthsList').innerHTML = _strengths.slice(-4)
        .map(s => `<li class="fade-in">${s}</li>`).join('') || '<li class="text-slate-400 italic">None yet</li>';

    if (_improvements.length) {
        $('improvementText').textContent = _improvements[_improvements.length - 1];
        $('improvementText').classList.remove('italic', 'text-slate-400');
    }

    if (ev.follow_up) {
        $('growthText').textContent = `"${ev.follow_up}"`;
        $('growthPrompt').classList.remove('hidden');
    }

    // Score chip
    const score = ev.score || 5;
    const chip = $('scoreChip');
    chip.classList.remove('hidden');
    chip.textContent = `${score}/10`;
    chip.className = `text-[10px] font-bold px-2 py-0.5 rounded-full border ${score >= 7 ? 'bg-emerald-50 text-emerald-700 border-emerald-100' : score >= 5 ? 'bg-amber-50 text-amber-700 border-amber-100' : 'bg-red-50 text-red-700 border-red-100'}`;

    // Sentiment
    let sent = '♥ Encouraging', scls = 'text-emerald-600';
    if (score >= 8) { sent = '🌟 Excellent'; scls = 'text-yellow-500'; }
    else if (score >= 6) { sent = '♥ Encouraging'; scls = 'text-emerald-600'; }
    else if (score >= 4) { sent = '📈 Improving'; scls = 'text-blue-500'; }
    else { sent = '💪 Keep Going'; scls = 'text-orange-500'; }
    $('sentimentEl').className = `text-sm font-bold ${scls}`;
    $('sentimentEl').textContent = sent;
}

// ─── Chat log ─────────────────────────────────────────────────────────────────
function addChat(role, text) {
    const log = $('chatLog');
    if (log.querySelector('.italic')) log.innerHTML = '';
    const div = document.createElement('div');
    div.className = 'fade-in';
    if (role === 'coach') {
        div.innerHTML = `
      <p class="text-[10px] text-blue-500 font-bold uppercase mb-1">Coach</p>
      <div class="bg-blue-50 border border-blue-100 rounded-xl rounded-tl-sm px-3 py-2 text-xs text-slate-700 leading-relaxed">${text}</div>`;
    } else {
        div.innerHTML = `
      <div class="text-right">
        <p class="text-[10px] text-slate-400 font-bold uppercase mb-1">You</p>
        <div class="inline-block bg-slate-100 border border-slate-200 rounded-xl rounded-tr-sm px-3 py-2 text-xs text-slate-700 leading-relaxed text-left">${text}</div>
      </div>`;
    }
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

// ─── Finish ───────────────────────────────────────────────────────────────────
async function finishInterview(fromServer = false) {
    stopVAD();
    clearInterval(IC.timerInterval);
    if (_faceCheckInterval) clearInterval(_faceCheckInterval);
    if (IC.cameraStream) IC.cameraStream.getTracks().forEach(t => t.stop());
    if (IC.micStream) IC.micStream.getTracks().forEach(t => t.stop());
    if (IC.audioCtx) IC.audioCtx.close().catch(() => { });

    $('loadingOverlay').classList.remove('hidden');
    $('loadingMsg').textContent = 'Generating your performance report…';

    if (!fromServer && IC.ws?.readyState === WebSocket.OPEN) {
        IC.ws.send(JSON.stringify({ type: 'finish' }));
        // Wait briefly for server to process
        await new Promise(r => setTimeout(r, 2000));
    } else if (IC.ws?.readyState === WebSocket.OPEN) {
        IC.ws.close();
    }
    window.location.href = '/report';
}

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
    $('userLabel').textContent = IC.name || 'You';
    $('sessionLabel').textContent = `${(IC.difficulty || '').toUpperCase()} · ${(IC.topic || '').toUpperCase()}`;
    setAIState('connecting');

    $('loadingMsg').textContent = 'Starting camera…';
    await setupWebcam();

    $('loadingMsg').textContent = 'Setting up microphone…';
    await setupMic();

    startTimer();
    $('chatLog').innerHTML = '';
    setAIState('connecting');

    $('loadingMsg').textContent = 'Connecting to AI coach…';
    connectWebSocket();

    // Hide overlay after WS sends first question (short delay)
    setTimeout(() => $('loadingOverlay').classList.add('hidden'), 3500);
}

document.addEventListener('DOMContentLoaded', () => setTimeout(init, 250));
