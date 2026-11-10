package com.gabstra.myworkoutassistant.data

import com.gabstra.myworkoutassistant.shared.datalayer.WorkoutSessionCommand
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * Carries phone-sent live session commands to the running [AppViewModel].
 *
 * The DataLayer service and the workout UI are separate components, so the service publishes here
 * and the view model collects. Replay of one keeps a command that arrives before the UI is wired;
 * freshness is checked on the receiving side.
 */
object WorkoutSessionCommandBus {
    private val _commands = MutableSharedFlow<WorkoutSessionCommand>(
        replay = 1,
        extraBufferCapacity = 0
    )
    val commands: SharedFlow<WorkoutSessionCommand> = _commands.asSharedFlow()

    fun publish(command: WorkoutSessionCommand) {
        _commands.tryEmit(command)
    }
}
