package com.voicecloneshield.app

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class AnalysisResult(
    val isFake: Boolean,
    val fakeScore: Double,
    val realScore: Double,
    val threatLevel: String,
    val summary: String,
    val rawJson: String
)

object ApiClient {
    private const val TAG = "ApiClient"

    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    suspend fun analyzeAudioWav(
        serverBaseUrl: String,
        wavBytes: ByteArray
    ): AnalysisResult? = withContext(Dispatchers.IO) {
        try {
            val cleanUrl = serverBaseUrl.trimEnd('/') + "/api/analyze"
            val requestBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart(
                    "file",
                    "call_chunk.wav",
                    wavBytes.toRequestBody("audio/wav".toMediaTypeOrNull())
                )
                .build()

            val request = Request.Builder()
                .url(cleanUrl)
                .post(requestBody)
                .build()

            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                Log.e(TAG, "Backend returned error code: ${response.code}")
                return@withContext null
            }

            val responseBody = response.body?.string() ?: return@withContext null
            val json = JSONObject(responseBody)

            val isFake = json.optBoolean("is_fake", false)
            val fakeScore = json.optDouble("fake_score", 0.0)
            val realScore = json.optDouble("real_score", 0.0)
            val threatLevel = json.optString("threat_level", if (isFake) "CRITICAL" else "LOW")
            val summary = json.optString("summary", "Analysis complete")

            AnalysisResult(
                isFake = isFake,
                fakeScore = fakeScore,
                realScore = realScore,
                threatLevel = threatLevel,
                summary = summary,
                rawJson = responseBody
            )
        } catch (e: Exception) {
            Log.e(TAG, "Failed to analyze audio chunk: ${e.message}", e)
            null
        }
    }
}
