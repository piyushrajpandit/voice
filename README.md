# 🛡️ Voice Clone Shield - Native Android App

An enterprise-grade Android companion application for **Voice Clone Shield**, mimicking the real-time call interception architecture used by **Truecaller** and **Google Call Screen**.

---

## 🌟 Key Architecture & Features

1. **Android `CallScreeningService` (API 29+)**:
   - Integrates directly with the Android Telecom Framework.
   - Intercepts incoming cellular calls **before or as the phone rings**.
   - Extracts caller metadata (e.g. `+1 412 754 7405`) and triggers defensive pipelines.

2. **Heads-Up Floating Call Overlay (`SYSTEM_ALERT_WINDOW`)**:
   - Renders a dark glassmorphic cybersecurity HUD directly over the native incoming call and active dialer screens.
   - Displays real-time spoof probability (e.g., `🚨 96% AI Synthetic Clone Detected`).
   - Quick response controls: **End Call**, **Mute**, and **Trigger Safeword Challenge**.

3. **Background Acoustic Streamer (`AudioRecord` 16kHz)**:
   - Streams live audio slices from the speakerphone / microphone directly to the FastAPI Neural Spoof Detection API (`/api/analyze`).
   - Parses probability scores dynamically and triggers haptic alert vibrations if a scam voice is detected.

4. **Investor & Judge Demo Mode**:
   - Built-in **"Simulate Incoming Scam Call"** one-tap test button that instantly launches the live floating HUD for presentations without requiring a second phone.

---

## 📱 How to Run & Install on an Android Phone

### Step 1: Open in Android Studio
1. Launch **Android Studio**.
2. Click **Open** and select the folder:
   `/Users/piyushraj/.gemini/antigravity-ide/scratch/voice-clone-shield-android`
3. Allow Gradle to sync dependencies (OkHttp, AndroidX, Material Design).

### Step 2: Configure Your Backend Server URL
1. In the app's Main Dashboard, enter your Voice Clone Shield backend URL:
   - **Local Wi-Fi IP**: e.g., `http://192.168.1.X:8000`
   - **Android Emulator**: `http://10.0.2.2:8000`
   - **Production / Render**: `https://your-app.onrender.com`
2. Tap **Save Server URL**.

### Step 3: Grant Required Android Permissions
Tap the three configuration buttons on the dashboard:
1. **Set as Default Call Screening App**: Android will prompt to assign *Voice Clone Shield* as the default caller ID & spam screening provider.
2. **Allow Floating Call HUD**: Grants permission to draw over other apps (`SYSTEM_ALERT_WINDOW`).
3. **Allow Microphone**: Grants access to real-time audio analysis.

---

## ⚡ How to Demo to Judges or Investors

### Method 1: Instant Simulation Mode (10-Second Pitch Demo)
1. Tap **⚡ Simulate Incoming Scam Call HUD**.
2. The phone will instantly trigger haptic vibrations and display the floating **AI Voice Clone Threat Card** over the screen.
3. Show the judges how it provides live synthetic confidence scores, caller identification, and a one-tap Safeword challenge!

### Method 2: Live Real Call Demo
1. Make a real phone call to your Android device from another phone.
2. The Android `CallScreeningService` will automatically detect the incoming ring and display the floating Voice Clone Shield HUD.
3. As the caller speaks, the app continuously validates the voice authenticity!
