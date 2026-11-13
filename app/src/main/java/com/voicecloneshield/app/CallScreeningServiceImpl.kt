package com.voicecloneshield.app

import android.content.Intent
import android.os.Build
import android.telecom.Call
import android.telecom.CallScreeningService
import android.util.Log

class CallScreeningServiceImpl : CallScreeningService() {

    companion object {
        private const val TAG = "CallScreeningService"
    }

    override fun onScreenCall(callDetails: Call.Details) {
        val phoneNumber = callDetails.handle?.schemeSpecificPart ?: "Unknown Caller"
        val isIncoming = callDetails.callDirection == Call.Details.DIRECTION_INCOMING

        Log.i(TAG, "Screening incoming call from: $phoneNumber (Incoming: $isIncoming)")

        // 1. Launch the Floating HUD Overlay to alert the user immediately
        val overlayIntent = Intent(this, CallShieldOverlayService::class.java).apply {
            putExtra(CallShieldOverlayService.EXTRA_CALLER_NUMBER, phoneNumber)
            putExtra(CallShieldOverlayService.EXTRA_SIMULATED, false)
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(overlayIntent)
        } else {
            startService(overlayIntent)
        }

        // 2. Respond to the Android Telecom framework
        // (Allow the call to ring normally while our Shield analyzes the voice in real-time)
        val response = CallResponse.Builder()
            .setDisallowCall(false)
            .setRejectCall(false)
            .setSkipCallLog(false)
            .setSkipNotification(false)
            .build()

        respondToCall(callDetails, response)
    }
}
