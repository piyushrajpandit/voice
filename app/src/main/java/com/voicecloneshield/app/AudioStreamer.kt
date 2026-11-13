package com.voicecloneshield.app

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import kotlinx.coroutines.*
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

class AudioStreamer(
    private val onChunkReady: (ByteArray) -> Unit
) {
    companion object {
        private const val TAG = "AudioStreamer"
        private const val SAMPLE_RATE = 16000
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        private const val CHUNK_SECONDS = 3 // 3 second audio slices
    }

    private var audioRecord: AudioRecord? = null
    private var isRecording = false
    private var recordingJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    @SuppressLint("MissingPermission")
    fun startStreaming() {
        if (isRecording) return

        val minBufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT)
        val bufferSize = maxOf(minBufferSize, SAMPLE_RATE * 2)

        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                SAMPLE_RATE,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
                bufferSize
            )

            if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                // Fallback to standard MIC if VOICE_COMMUNICATION is restricted
                audioRecord = AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    SAMPLE_RATE,
                    CHANNEL_CONFIG,
                    AUDIO_FORMAT,
                    bufferSize
                )
            }

            audioRecord?.startRecording()
            isRecording = true
            Log.d(TAG, "Audio recording started at 16kHz")

            recordingJob = scope.launch {
                val chunkSize = SAMPLE_RATE * 2 * CHUNK_SECONDS // 16k * 2 bytes * 3 sec = 96,000 bytes
                val rawPcmBuffer = ByteArray(chunkSize)
                var bytesReadTotal = 0

                while (isActive && isRecording) {
                    val read = audioRecord?.read(
                        rawPcmBuffer,
                        bytesReadTotal,
                        chunkSize - bytesReadTotal
                    ) ?: 0

                    if (read > 0) {
                        bytesReadTotal += read
                        if (bytesReadTotal >= chunkSize) {
                            val wavBytes = createWavFile(rawPcmBuffer, SAMPLE_RATE)
                            onChunkReady(wavBytes)
                            bytesReadTotal = 0
                        }
                    } else {
                        delay(50)
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error starting AudioStreamer: ${e.message}", e)
        }
    }

    fun stopStreaming() {
        isRecording = false
        recordingJob?.cancel()
        try {
            audioRecord?.stop()
            audioRecord?.release()
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping AudioStreamer: ${e.message}")
        }
        audioRecord = null
    }

    private fun createWavFile(pcmData: ByteArray, sampleRate: Int): ByteArray {
        val totalAudioLen = pcmData.size.toLong()
        val totalDataLen = totalAudioLen + 36
        val channels = 1
        val byteRate = (sampleRate * 2 * channels).toLong()

        val out = ByteArrayOutputStream()
        val header = ByteArray(44)
        val buffer = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN)

        // RIFF header
        buffer.put('R'.code.toByte())
        buffer.put('I'.code.toByte())
        buffer.put('F'.code.toByte())
        buffer.put('F'.code.toByte())
        buffer.putInt(totalDataLen.toInt())
        buffer.put('W'.code.toByte())
        buffer.put('A'.code.toByte())
        buffer.put('V'.code.toByte())
        buffer.put('E'.code.toByte())

        // fmt chunk
        buffer.put('f'.code.toByte())
        buffer.put('m'.code.toByte())
        buffer.put('t'.code.toByte())
        buffer.put(' '.code.toByte())
        buffer.putInt(16) // Subchunk1Size (16 for PCM)
        buffer.putShort(1.toShort()) // AudioFormat (1 for PCM)
        buffer.putShort(channels.toShort())
        buffer.putInt(sampleRate)
        buffer.putInt(byteRate.toInt())
        buffer.putShort((channels * 2).toShort()) // block align
        buffer.putShort(16.toShort()) // bits per sample

        // data chunk
        buffer.put('d'.code.toByte())
        buffer.put('a'.code.toByte())
        buffer.put('t'.code.toByte())
        buffer.put('a'.code.toByte())
        buffer.putInt(totalAudioLen.toInt())

        out.write(header)
        out.write(pcmData)
        return out.toByteArray()
    }
}
