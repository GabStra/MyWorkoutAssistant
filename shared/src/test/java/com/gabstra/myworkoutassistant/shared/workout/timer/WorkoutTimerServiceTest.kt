package com.gabstra.myworkoutassistant.shared.workout.timer

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

@OptIn(ExperimentalCoroutinesApi::class)
class WorkoutTimerServiceTest {

    @Test
    fun timedDuration_usesMonotonicProgression_andRespectsPauseResume() = runTest {
        val setId = UUID.randomUUID()
        val state = WorkoutState.Set(
            exerciseId = UUID.randomUUID(),
            set = TimedDurationSet(setId, timeInMillis = 5_000, autoStart = false, autoStop = true),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(TimedDurationSetData(5_000, 5_000, autoStart = false, autoStop = true)),
            hasNoHistory = true,
            startTime = LocalDateTime.now(),
            skipped = false,
            currentBodyWeight = 70.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null
        )

        val service = WorkoutTimerService(
            viewModelScope = backgroundScope,
            isPaused = { false },
            monotonicNowMs = { testScheduler.currentTime }
        )

        service.registerTimer(
            state = state,
            callbacks = WorkoutTimerService.TimerCallbacks({}, {}, {})
        )

        advanceTimeBy(1_200)
        runCurrent()
        val uiAfterRun = service.timerUiStates.value[setId]
        assertNotNull(uiAfterRun)
        assertEquals(3_800, (state.currentSetData as TimedDurationSetData).endTimer)
        assertEquals(3, uiAfterRun!!.displaySeconds)
        assertTrue(uiAfterRun.isRunning)

        service.pauseTimer(setId)
        advanceTimeBy(1_000)
        runCurrent()
        assertEquals(3_800, (state.currentSetData as TimedDurationSetData).endTimer)

        service.resumeTimer(setId)
        advanceTimeBy(1_000)
        runCurrent()
        assertEquals(2_800, (state.currentSetData as TimedDurationSetData).endTimer)
        assertEquals(2, service.timerUiStates.value[setId]?.displaySeconds)
    }

    @Test
    fun restTimer_flowStateStaysAlignedWithServiceProgression() = runTest {
        val setId = UUID.randomUUID()
        val restState = WorkoutState.Rest(
            set = RestSet(setId, timeInSeconds = 10),
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(startTimer = 10, endTimer = 10)),
            startTime = LocalDateTime.now()
        )

        val service = WorkoutTimerService(
            viewModelScope = backgroundScope,
            isPaused = { false },
            monotonicNowMs = { testScheduler.currentTime }
        )

        service.registerTimer(
            state = restState,
            callbacks = WorkoutTimerService.TimerCallbacks({}, {}, {})
        )

        advanceTimeBy(2_500)
        runCurrent()

        val setData = restState.currentSetData as RestSetData
        val uiState = service.timerUiStates.value[setId]
        assertEquals(8, setData.endTimer)
        assertEquals(8, uiState?.displaySeconds)
        assertEquals(8_000, uiState?.displayMillis)
    }

    @Test
    fun unregisterTimer_clearsUiState() = runTest {
        val setId = UUID.randomUUID()
        val restState = WorkoutState.Rest(
            set = RestSet(setId, timeInSeconds = 5),
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(startTimer = 5, endTimer = 5)),
            startTime = LocalDateTime.now()
        )

        val service = WorkoutTimerService(
            viewModelScope = backgroundScope,
            isPaused = { false },
            monotonicNowMs = { testScheduler.currentTime }
        )

        service.registerTimer(
            state = restState,
            callbacks = WorkoutTimerService.TimerCallbacks({}, {}, {})
        )

        assertNotNull(service.timerUiStates.value[setId])
        assertTrue(service.isTimerRegistered(setId))

        service.unregisterTimer(setId)

        assertNull(service.timerUiStates.value[setId])
        assertFalse(service.isTimerRegistered(setId))
    }
}
