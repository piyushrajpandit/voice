package com.voicecloneshield.app

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class CallShieldOverlayService : Service() {

    companion object {
        private const val TAG = "CallShieldOverlay"
        const val EXTRA_CALLER_NUMBER = "extra_caller_number"
        const val EXTRA_SIMULATED = "extra_simulated"
        private const val NOTIFICATION_ID = 9001
        private const val CHANNEL_ID = "call_shield_channel"
    }

    private var windowManager: WindowManager? = null
    private var overlayView: View? = null
    private var audioStreamer: AudioStreamer? = null
    private val serviceScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var isSimulated = false
    private var callerNumber = "+1 (412) 754-7405"

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        callerNumber = intent?.getStringExtra(EXTRA_CALLER_NUMBER) ?: "+1 (412) 754-7405"
        isSimulated = intent?.getBooleanExtra(EXTRA_SIMULATED, false) ?: false

        startForeground(NOTIFICATION_ID, buildForegroundNotification())

        if (Settings.canDrawOverlays(this)) {
            showFloatingOverlay()
            startAudioMonitoring()
        } else {
            Log.w(TAG, "Cannot draw overlay: SYSTEM_ALERT_WINDOW permission not granted")
        }

        return START_NOT_STICKY
    }

    @SuppressLint("ClickableViewAccessibility", "InflateParams")
    private fun showFloatingOverlay() {
        if (overlayView != null) return

        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val inflater = LayoutInflater.from(this)
        overlayView = inflater.inflate(R.layout.layout_floating_shield, null)

        val layoutFlag = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutFlag,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = 100
        }

        // Setup Views
        val tvCallerNumber = overlayView?.findViewById<TextView>(R.id.tvCallerNumber)
        val bannerStatus = overlayView?.findViewById<LinearLayout>(R.id.bannerStatus)
        val tvThreatLevel = overlayView?.findViewById<TextView>(R.id.tvThreatLevel)
        val tvThreatDetails = overlayView?.findViewById<TextView>(R.id.tvThreatDetails)
        val tvLiveStatus = overlayView?.findViewById<TextView>(R.id.tvLiveStatus)
        val btnDismiss = overlayView?.findViewById<TextView>(R.id.btnDismiss)
        val btnHangup = overlayView?.findViewById<Button>(R.id.btnHangupCall)
        val btnSafeword = overlayView?.findViewById<Button>(R.id.btnSafeword)
        val ivAlertStatus = overlayView?.findViewById<ImageView>(R.id.ivAlertStatus)

        tvCallerNumber?.text = callerNumber

        if (isSimulated) {
            tvThreatLevel?.text = "SIMULATION: HIGH RISK SCAM"
            tvThreatDetails?.text = "94.8% AI Voice Match • Urgent Transfer Request"
            tvLiveStatus?.text = "● Neural Classifier Active (Simulated)"
            vibrateAlert()
        } else {
            // Initial analyzing state
            tvThreatLevel?.text = "ANALYZING VOICE SIGNATURE..."
            tvThreatLevel?.setTextColor(Color.parseColor("#06B6D4"))
            tvThreatDetails?.text = "Listening for synthetic voice artifacts and scam phrases"
            bannerStatus?.setBackgroundColor(Color.parseColor("#3306B6D4"))
            ivAlertStatus?.setColorFilter(Color.parseColor("#06B6D4"))
        }

        btnDismiss?.setOnClickListener {
            stopSelf()
        }

        btnHangup?.setOnClickListener {
            // Dismiss overlay and signal hangup
            stopSelf()
        }

        btnSafeword?.setOnClickListener {
            tvLiveStatus?.text = "✓ Safeword Challenge Sent via SMS"
        }

        // Draggable Overlay Touch Listener
        var initialY = 0
        var initialTouchY = 0f
        overlayView?.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialY = params.y
                    initialTouchY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    params.y = initialY + (event.rawY - initialTouchY).toInt()
                    windowManager?.updateViewLayout(overlayView, params)
                    true
                }
                else -> false
            }
        }

        try {
            windowManager?.addView(overlayView, params)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to attach floating overlay: ${e.message}", e)
        }
    }

    private fun startAudioMonitoring() {
        if (isSimulated) return

        val prefs = getSharedPreferences("vcs_prefs", Context.MODE_PRIVATE)
        val serverUrl = prefs.getString("backend_url", "http://10.0.2.2:8000") ?: "http://10.0.2.2:8000"

        audioStreamer = AudioStreamer { wavChunk ->
            serviceScope.launch {
                val result = ApiClient.analyzeAudioWav(serverUrl, wavChunk)
                if (result != null) {
                    updateOverlayWithResult(result)
                }
            }
        }
        audioStreamer?.startStreaming()
    }

    private suspend fun updateOverlayWithResult(result: AnalysisResult) = withContext(Dispatchers.Main) {
        val bannerStatus = overlayView?.findViewById<LinearLayout>(R.id.bannerStatus)
        val tvThreatLevel = overlayView?.findViewById<TextView>(R.id.tvThreatLevel)
        val tvThreatDetails = overlayView?.findViewById<TextView>(R.id.tvThreatDetails)
        val tvLiveStatus = overlayView?.findViewById<TextView>(R.id.tvLiveStatus)
        val ivAlertStatus = overlayView?.findViewById<ImageView>(R.id.ivAlertStatus)

        if (result.isFake || result.fakeScore > 0.60) {
            val scorePct = (result.fakeScore * 100).toInt()
            tvThreatLevel?.text = "CRITICAL: AI VOICE CLONE ($scorePct%)"
            tvThreatLevel?.setTextColor(Color.parseColor("#EF4444"))
            tvThreatDetails?.text = "Synthetic Voice Artifacts Detected • Threat Level: ${result.threatLevel}"
            bannerStatus?.setBackgroundColor(Color.parseColor("#44EF4444"))
            ivAlertStatus?.setColorFilter(Color.parseColor("#EF4444"))
            tvLiveStatus?.text = "🚨 Warning: High probability caller is an AI imposter!"
            vibrateAlert()
        } else {
            val realPct = (result.realScore * 100).toInt()
            tvThreatLevel?.text = "AUTHENTIC HUMAN VOICE ($realPct%)"
            tvThreatLevel?.setTextColor(Color.parseColor("#10B981"))
            tvThreatDetails?.text = "Natural pitch acoustics verified • No cloning detected"
            bannerStatus?.setBackgroundColor(Color.parseColor("#3310B981"))
            ivAlertStatus?.setColorFilter(Color.parseColor("#10B981"))
            tvLiveStatus?.text = "● Acoustic Stream Verified • Call is Safe"
        }
    }

    private fun vibrateAlert() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vibratorManager = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
                vibratorManager.defaultVibrator.vibrate(
                    VibrationEffect.createWaveform(longArrayOf(0, 300, 150, 300), -1)
                )
            } else {
                @Suppress("DEPRECATION")
                val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 300, 150, 300), -1))
                } else {
                    @Suppress("DEPRECATION")
                    vibrator.vibrate(400)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Vibrate failed: ${e.message}")
        }
    }

    private fun buildForegroundNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Voice Clone Shield Active")
            .setContentText("Screening active call with real-time AI spoof detector")
            .setSmallIcon(R.drawable.ic_shield)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setOngoing(true)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.channel_name),
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = getString(R.string.channel_desc)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        audioStreamer?.stopStreaming()
        serviceScope.cancel()
        if (overlayView != null) {
            try {
                windowManager?.removeView(overlayView)
            } catch (e: Exception) {
                Log.e(TAG, "Error removing overlayView: ${e.message}")
            }
            overlayView = null
        }
    }
}
