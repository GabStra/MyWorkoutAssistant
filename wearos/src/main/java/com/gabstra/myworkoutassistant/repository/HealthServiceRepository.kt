package com.gabstra.myworkoutassistant.repository
/*
import android.content.Context
import android.util.Log
import androidx.concurrent.futures.await
import androidx.health.services.client.ExerciseClient
import androidx.health.services.client.ExerciseUpdateCallback
import androidx.health.services.client.HealthServices
import androidx.health.services.client.MeasureCallback
import androidx.health.services.client.data.Availability
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.DataTypeAvailability
import androidx.health.services.client.data.DeltaDataType
import androidx.health.services.client.data.ExerciseConfig
import androidx.health.services.client.data.ExerciseLapSummary
import androidx.health.services.client.data.ExerciseTrackedStatus
import androidx.health.services.client.data.ExerciseType
import androidx.health.services.client.data.ExerciseTypeCapabilities
import androidx.health.services.client.data.ExerciseUpdate
import androidx.health.services.client.data.LocationAvailability
import androidx.health.services.client.data.SampleDataPoint
import androidx.health.services.client.data.WarmUpConfig
import androidx.health.services.client.endExercise
import androidx.health.services.client.getCapabilities
import androidx.health.services.client.getCurrentExerciseInfo
import androidx.health.services.client.pauseExercise
import androidx.health.services.client.prepareExercise
import androidx.health.services.client.resumeExercise
import androidx.health.services.client.startExercise
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.channels.trySendBlocking
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.runBlocking

/**
 * Entry point for [HealthServicesClient] APIs. This also provides suspend functions around
 * those APIs to enable use in coroutines.
 */
class HealthServicesRepository(context: Context) {
    private val healthServicesClient = HealthServices.getClient(context)
    private val exerciseClient: ExerciseClient = healthServicesClient.exerciseClient

    suspend fun getExerciseCapabilities(): ExerciseTypeCapabilities? {
        val capabilities = exerciseClient.getCapabilities()

        return if (ExerciseType.WORKOUT in capabilities.supportedExerciseTypes) {
            capabilities.getExerciseTypeCapabilities(ExerciseType.WORKOUT)
        } else {
            null
        }
    }

    suspend fun startExercise() {
        // Types for which we want to receive metrics. Only ask for ones that are supported.
        val capabilities = getExerciseCapabilities() ?: return

        val dataTypes = setOf(
            DataType.HEART_RATE_BPM,
        ).intersect(capabilities.supportedDataTypes)


        val config = ExerciseConfig(
            exerciseType = ExerciseType.RUNNING,
            dataTypes = dataTypes,
            isAutoPauseAndResumeEnabled = true,
            isGpsEnabled = false,
        )

        exerciseClient.startExercise(config)
    }

    /***
     * Note: don't call this method from outside of ExerciseService.kt
     * when acquiring calories or distance.
     */
    suspend fun prepareExercise() {
        val warmUpConfig = WarmUpConfig(
            exerciseType = ExerciseType.RUNNING,
            dataTypes = setOf(DataType.HEART_RATE_BPM)
        )

        exerciseClient.prepareExercise(warmUpConfig)
    }

    suspend fun endExercise() {
        //logger.log("Ending exercise")
        exerciseClient.endExercise()
    }

    suspend fun pauseExercise() {
        //logger.log("Pausing exercise")
        exerciseClient.pauseExercise()
    }

    suspend fun resumeExercise() {
        //logger.log("Resuming exercise")
        exerciseClient.resumeExercise()
    }

    private suspend fun ExerciseClient.isExerciseInProgress(): Boolean {
        val exerciseInfo = getCurrentExerciseInfo()
        return exerciseInfo.exerciseTrackedStatus == ExerciseTrackedStatus.OWNED_EXERCISE_IN_PROGRESS
    }

    suspend fun isExerciseInProgress() =
        exerciseClient.isExerciseInProgress()

    /**
     * Returns a cold flow. When activated, the flow will register a callback for heart rate data
     * and start to emit messages. When the consuming coroutine is cancelled, the measure callback
     * is unregistered.
     *
     * [callbackFlow] is used to bridge between a callback-based API and Kotlin flows.
     */
    fun exerciseUpdateFlow() = callbackFlow {
        val callback = object : ExerciseUpdateCallback {
            override fun onExerciseUpdateReceived(update: ExerciseUpdate) {
                trySendBlocking(ExerciseMessage.ExerciseUpdateMessage(update))
            }

            override fun onLapSummaryReceived(lapSummary: ExerciseLapSummary) {
                trySendBlocking(ExerciseMessage.LapSummaryMessage(lapSummary))
            }

            override fun onRegistered() {
            }

            override fun onRegistrationFailed(throwable: Throwable) {
                TODO("Not yet implemented")
            }

            override fun onAvailabilityChanged(
                dataType: DataType<*, *>, availability: Availability
            ) {
                if(availability is DataTypeAvailability){
                    trySendBlocking(MeasureMessage.MeasureAvailability(availability))
                }

                if (availability is LocationAvailability) {
                    trySendBlocking(ExerciseMessage.LocationAvailabilityMessage(availability))
                }
            }
        }

        exerciseClient.setUpdateCallback(callback)
        awaitClose {
            // Ignore async result
            exerciseClient.clearUpdateCallbackAsync(callback)
        }
    }
}

sealed class ExerciseMessage {
    class ExerciseUpdateMessage(val exerciseUpdate: ExerciseUpdate) : ExerciseMessage()
    class LapSummaryMessage(val lapSummary: ExerciseLapSummary) : ExerciseMessage()
    class LocationAvailabilityMessage(val locationAvailability: LocationAvailability) :
        ExerciseMessage()
}

sealed class MeasureMessage {
    class MeasureAvailability(val availability: DataTypeAvailability) : MeasureMessage()
    class MeasureData(val data: List<SampleDataPoint<Double>>) : MeasureMessage()
}
*/