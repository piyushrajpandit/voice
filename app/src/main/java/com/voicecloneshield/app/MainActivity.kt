package com.voicecloneshield.app

import android.Manifest
import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var btnScreeningRole: Button
    private lateinit var btnOverlayPermission: Button
    private lateinit var btnMicPermission: Button
    private lateinit var btnSimulateCall: Button
    private lateinit var etBackendUrl: EditText
    private lateinit var btnSaveConfig: Button
    private lateinit var tvStatusBadge: TextView

    private val screeningRoleLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        updatePermissionStatuses()
    }

    private val overlayPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        updatePermissionStatuses()
    }

    private val micPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) {
        updatePermissionStatuses()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        initViews()
        loadSavedConfig()
        setupListeners()
    }

    override fun onResume() {
        super.onResume()
        updatePermissionStatuses()
    }

    private fun initViews() {
        btnScreeningRole = findViewById(R.id.btnScreeningRole)
        btnOverlayPermission = findViewById(R.id.btnOverlayPermission)
        btnMicPermission = findViewById(R.id.btnMicPermission)
        btnSimulateCall = findViewById(R.id.btnSimulateCall)
        etBackendUrl = findViewById(R.id.etBackendUrl)
        btnSaveConfig = findViewById(R.id.btnSaveConfig)
        tvStatusBadge = findViewById(R.id.tvStatusBadge)
    }

    private fun loadSavedConfig() {
        val prefs = getSharedPreferences("vcs_prefs", Context.MODE_PRIVATE)
        val savedUrl = prefs.getString("backend_url", "https://voice-clone-shield.onrender.com")
        etBackendUrl.setText(savedUrl)
    }

    private fun setupListeners() {
        btnScreeningRole.setOnClickListener {
            requestCallScreeningRole()
        }

        btnOverlayPermission.setOnClickListener {
            requestOverlayPermission()
        }

        btnMicPermission.setOnClickListener {
            micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }

        btnSaveConfig.setOnClickListener {
            val url = etBackendUrl.text.toString().trim()
            if (url.isNotEmpty()) {
                val prefs = getSharedPreferences("vcs_prefs", Context.MODE_PRIVATE)
                prefs.edit().putString("backend_url", url).apply()
                Toast.makeText(this, "Backend URL saved successfully!", Toast.LENGTH_SHORT).show()
            }
        }

        btnSimulateCall.setOnClickListener {
            if (!Settings.canDrawOverlays(this)) {
                Toast.makeText(this, "Please grant Floating Window permission first!", Toast.LENGTH_LONG).show()
                requestOverlayPermission()
                return@setOnClickListener
            }

            val intent = Intent(this, CallShieldOverlayService::class.java).apply {
                putExtra(CallShieldOverlayService.EXTRA_CALLER_NUMBER, "+1 (412) 754-7405")
                putExtra(CallShieldOverlayService.EXTRA_SIMULATED, true)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
            Toast.makeText(this, "Simulating incoming call HUD...", Toast.LENGTH_SHORT).show()
        }
    }

    private fun requestCallScreeningRole() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val roleManager = getSystemService(RoleManager::class.java)
            if (roleManager != null && roleManager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)) {
                if (!roleManager.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)) {
                    val intent = roleManager.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING)
                    screeningRoleLauncher.launch(intent)
                } else {
                    Toast.makeText(this, "Already set as Default Call Screening app!", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun requestOverlayPermission() {
        if (!Settings.canDrawOverlays(this)) {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")
            )
            overlayPermissionLauncher.launch(intent)
        } else {
            Toast.makeText(this, "Floating Window permission already granted!", Toast.LENGTH_SHORT).show()
        }
    }

    private fun updatePermissionStatuses() {
        // 1. Call Screening Role
        val hasScreeningRole = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val roleManager = getSystemService(RoleManager::class.java)
            roleManager?.isRoleHeld(RoleManager.ROLE_CALL_SCREENING) == true
        } else false

        if (hasScreeningRole) {
            btnScreeningRole.text = "✓ 1. Call Screening Role Granted"
            btnScreeningRole.setBackgroundColor(ContextCompat.getColor(this, R.color.accent_green))
        }

        // 2. Overlay Permission
        val hasOverlay = Settings.canDrawOverlays(this)
        if (hasOverlay) {
            btnOverlayPermission.text = "✓ 2. Floating Window Granted"
            btnOverlayPermission.setTextColor(ContextCompat.getColor(this, R.color.accent_green))
        }

        // 3. Mic Permission
        val hasMic = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
        if (hasMic) {
            btnMicPermission.text = "✓ 3. Microphone Granted"
            btnMicPermission.setTextColor(ContextCompat.getColor(this, R.color.accent_green))
        }

        if (hasScreeningRole && hasOverlay && hasMic) {
            tvStatusBadge.text = "● SHIELD FULLY ARMED"
            tvStatusBadge.setTextColor(ContextCompat.getColor(this, R.color.accent_green))
        }
    }
}
