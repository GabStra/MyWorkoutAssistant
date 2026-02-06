package com.gabstra.myworkoutassistant.shared.workout.session

import android.util.Log
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import java.time.LocalDateTime

class WorkoutTimerRestoreService {
    fun restoreTimerForTimeSet(
        state: WorkoutState.Set,
        executedSetHistories: List<SetHistory>,
        logTag: String
    ) {
        val set = state.set
        val isTimeSet = set is TimedDurationSet || set is EnduranceSet
        if (!isTimeSet) return

        val historyIdentity = WorkoutStateQueries.stateHistoryIdentity(state) ?: return
        val setHistory = executedSetHistories.firstOrNull {
            WorkoutStateQueries.matchesSetHistory(
                it,
                historyIdentity.setId,
                historyIdentity.order,
                historyIdentity.exerciseId
            )
        }
        val now = LocalDateTime.now()

        when {
            set is TimedDurationSet -> restoreTimedDurationSetTimer(state, setHistory, now, logTag)
            set is EnduranceSet -> restoreEnduranceSetTimer(state, setHistory, now, logTag)
        }
    }

    private fun restoreTimedDurationSetTimer(
        state: WorkoutState.Set,
        setHistory: SetHistory?,
        now: LocalDateTime,
        logTag: String
    ) {
        val setData = if (setHistory?.setData is TimedDurationSetData) {
            setHistory.setData as TimedDurationSetData
        } else {
            val currentSetData = state.currentSetData as? TimedDurationSetData
            if (currentSetData != null && currentSetData.endTimer < currentSetData.startTimer && currentSetData.endTimer > 0) {
                Log.d(
                    logTag,
                    "Restoring timer from current state (no SetHistory): endTimer=${currentSetData.endTimer}, startTimer=${currentSetData.startTimer}"
                )
                currentSetData
            } else {
                Log.d(logTag, "No timer state found for TimedDurationSet - timer will start from beginning")
                return
            }
        }

        if (setData.endTimer < setData.startTimer && setData.endTimer > 0) {
            val elapsedMillis = setData.startTimer - setData.endTimer
            if (elapsedMillis > 0 && elapsedMillis <= setData.startTimer) {
                state.startTime = now.minusNanos((elapsedMillis * 1_000_000L).toLong())
                Log.d(logTag, "Restored TimedDurationSet timer: elapsed=${elapsedMillis}ms, remaining=${setData.endTimer}ms")
            } else {
                Log.w(logTag, "Invalid elapsed time calculated: ${elapsedMillis}ms for timer with startTimer=${setData.startTimer}ms")
            }
        } else {
            Log.d(logTag, "Timer not running or completed: endTimer=${setData.endTimer}, startTimer=${setData.startTimer}")
        }
    }

    private fun restoreEnduranceSetTimer(
        state: WorkoutState.Set,
        setHistory: SetHistory?,
        now: LocalDateTime,
        logTag: String
    ) {
        val setData = if (setHistory?.setData is EnduranceSetData) {
            setHistory.setData as EnduranceSetData
        } else {
            val currentSetData = state.currentSetData as? EnduranceSetData
            if (currentSetData != null && currentSetData.endTimer > 0) {
                Log.d(logTag, "Restoring timer from current state (no SetHistory): endTimer=${currentSetData.endTimer}")
                currentSetData
            } else {
                Log.d(logTag, "No timer state found for EnduranceSet - timer will start from beginning")
                return
            }
        }

        if (setData.endTimer > 0 && setData.endTimer <= setData.startTimer) {
            state.startTime = now.minusNanos((setData.endTimer * 1_000_000L).toLong())
            Log.d(logTag, "Restored EnduranceSet timer: elapsed=${setData.endTimer}ms")
        } else {
            Log.d(logTag, "Timer not running or invalid: endTimer=${setData.endTimer}, startTimer=${setData.startTimer}")
        }
    }
}


