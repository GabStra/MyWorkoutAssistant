package com.gabstra.myworkoutassistant.composables

import androidx.activity.compose.BackHandler
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.onLongClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.data.LongPressRepeatSpeedStage
import com.gabstra.myworkoutassistant.data.repeatActionOnLongPressOrTap
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.Red
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

internal const val WEAR_CONTROL_EDIT_INACTIVITY_TIMEOUT_MILLIS = 10_000L

// Hold latency before steps repeat, and how long a repeat must run before it
// switches to the coarse step (bigger jumps for the same finger time).
// Deliberately unhurried: a slow, careful tap must stay a single step, so the
// hold only starts repeating after a clearly intentional long press.
private const val REPEAT_THRESHOLD_MILLIS = 700L
internal const val COARSE_STEP_AFTER_MILLIS = 2_500L

/** Gentle ramp so fine adjustments stay controllable during the first seconds of a hold. */
private val VerticalControlSpeedStages = listOf(
    LongPressRepeatSpeedStage(holdTimeMillis = 0L, intervalMillis = 250L),
    LongPressRepeatSpeedStage(holdTimeMillis = 2_500L, intervalMillis = 180L),
    LongPressRepeatSpeedStage(holdTimeMillis = 5_000L, intervalMillis = 120L),
)

/** A sustained hold switches to the bigger step once it has repeated this long. */
internal fun shouldUseCoarseStep(elapsedHoldMillis: Long, hasCoarseStep: Boolean): Boolean =
    hasCoarseStep && elapsedHoldMillis >= COARSE_STEP_AFTER_MILLIS

@Composable
fun ControlButtonsVertical(
    modifier: Modifier,
    onMinusTap: () -> Unit,
    onMinusLongPress: () -> Unit,
    onPlusTap: () -> Unit,
    onPlusLongPress: () -> Unit,
    onMinusCoarse: (() -> Unit)? = null,
    onPlusCoarse: (() -> Unit)? = null,
    isMinusEnabled: Boolean = true,
    isPlusEnabled: Boolean = true,
    isResetEnabled: Boolean = true,
    onCloseClick: (() -> Unit)? = null,
    onResetClick: (() -> Unit)? = null,
    content: @Composable () -> Unit
){
    BackHandler(enabled = onCloseClick != null) {
        onCloseClick?.invoke()
    }

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .padding(horizontal = 20.dp),
            contentAlignment = Alignment.Center
        ) {
            content()
        }

        // Spacing equalises the *visible* gaps between the painted circles and the
        // screen edge (10dp each), since hit-box margins differ per row.
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 6.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            // Hit-box margins already add 3dp+4dp between the painted circles.
            verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterHorizontally),
            ) {
                // Tighter hit-box than the standard 62.5dp so the edited value keeps its height.
                ControlButton(
                    Icons.Filled.ArrowDownward, "Subtract", Red, isMinusEnabled,
                    onMinusTap, onMinusLongPress, onMinusCoarse,
                    iconTint = Color.White,
                    hitBoxSize = 56.dp,
                    buttonSize = WearStandardIconButtonSize,
                    iconSize = WearStandardIconButtonIconSize,
                )
                ControlButton(
                    Icons.Filled.ArrowUpward, "Add", Green, isPlusEnabled,
                    onPlusTap, onPlusLongPress, onPlusCoarse,
                    iconTint = Color.White,
                    hitBoxSize = 56.dp,
                    buttonSize = WearStandardIconButtonSize,
                    iconSize = WearStandardIconButtonIconSize,
                )
            }
            if (onCloseClick != null || onResetClick != null) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterHorizontally),
                ) {
                    onCloseClick?.let { closeClick ->
                        ControlButton(
                            Icons.Filled.Close, "Back",
                            MaterialTheme.colorScheme.surfaceContainerHigh, true,
                            closeClick, closeClick, null,
                        )
                    }
                    onResetClick?.let { resetClick ->
                        HoldToConfirmControlButton(
                            Icons.Filled.RestartAlt, "Reset",
                            isResetEnabled,
                            resetClick,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ControlButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    contentDescription: String,
    backgroundColor: Color,
    enabled: Boolean,
    onTap: () -> Unit,
    onLongPress: () -> Unit,
    onCoarse: (() -> Unit)? = null,
    iconTint: Color = MaterialTheme.colorScheme.onBackground,
    hitBoxSize: androidx.compose.ui.unit.Dp = WearSecondaryIconButtonHitBoxSize,
    buttonSize: androidx.compose.ui.unit.Dp = WearSecondaryIconButtonSize,
    iconSize: androidx.compose.ui.unit.Dp = WearSecondaryIconButtonIconSize,
) {
    var isPressed by remember { mutableStateOf(false) }
    val buttonBackground by animateColorAsState(
        targetValue = if (enabled && isPressed) darkenButtonColor(backgroundColor) else backgroundColor,
        label = "control button press",
    )
    val iconColor by animateColorAsState(
        targetValue = if (enabled && isPressed) darkenButtonColor(iconTint) else iconTint,
        label = "control button icon press",
    )
    Box(
        modifier = Modifier
            .size(hitBoxSize)
            .alpha(if (enabled) 1f else 0.45f)
            .semantics(mergeDescendants = true) {
                this.contentDescription = contentDescription
                role = Role.Button
                if (!enabled) disabled()
                onClick(
                    label = contentDescription
                ) {
                    if (!enabled) return@onClick false
                    onTap()
                    true
                }
                onLongClick(
                    label = contentDescription
                ) {
                    if (!enabled) return@onLongClick false
                    onLongPress()
                    true
                }
            }
            .repeatActionOnLongPressOrTap(
                thresholdMillis = REPEAT_THRESHOLD_MILLIS,
                intervalMillis = 250,
                speedStages = VerticalControlSpeedStages,
                enabled = enabled,
                onPressedChange = { isPressed = it },
                onAction = { elapsedHoldMillis ->
                    if (shouldUseCoarseStep(elapsedHoldMillis, onCoarse != null)) onCoarse?.invoke() else onLongPress()
                },
                onTap = onTap
            ),
        contentAlignment = Alignment.Center
    ) {
        Box(
            modifier = Modifier
                .size(buttonSize)
                .background(buttonBackground, CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                modifier = Modifier.size(iconSize),
                imageVector = icon,
                contentDescription = null,
                tint = iconColor,
            )
        }
    }
}

/**
 * Hold-to-confirm reset, mirroring the confirm button of CustomDialogYesOnLongPress:
 * a progress ring fills while held, the action fires only when the hold completes,
 * and releasing early cancels. Fires never on a plain tap.
 */
@Composable
private fun HoldToConfirmControlButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    contentDescription: String,
    enabled: Boolean,
    onConfirmed: () -> Unit,
) {
    val holdDurationMillis = LocalViewConfiguration.current.longPressTimeoutMillis
        .coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
    val coroutineScope = rememberWearCoroutineScope()
    val holdProgress = remember { Animatable(0f) }
    var holdJob by remember { mutableStateOf<Job?>(null) }
    var isPressed by remember { mutableStateOf(false) }
    val buttonBackground by animateColorAsState(
        targetValue = if (enabled && isPressed) darkenButtonColor(MaterialTheme.colorScheme.primary)
        else MaterialTheme.colorScheme.primary,
        label = "reset button press",
    )

    fun startHold() {
        if (!enabled) return
        isPressed = true
        holdJob?.cancel()
        holdJob = coroutineScope.launch {
            holdProgress.snapTo(0f)
            holdProgress.animateTo(
                targetValue = 1f,
                animationSpec = tween(durationMillis = holdDurationMillis, easing = LinearEasing)
            )
            onConfirmed()
            holdProgress.snapTo(0f)
        }
    }

    fun cancelHold() {
        holdJob?.cancel()
        holdJob = null
        isPressed = false
        coroutineScope.launch { holdProgress.snapTo(0f) }
    }

    Box(
        modifier = Modifier
            .size(WearSecondaryIconButtonHitBoxSize)
            .alpha(if (enabled) 1f else 0.45f)
            .semantics(mergeDescendants = true) {
                this.contentDescription = contentDescription
                role = Role.Button
                if (!enabled) disabled()
                onLongClick(
                    label = contentDescription
                ) { enabled }
            }
            .pointerInput(enabled) {
                detectTapGestures(
                    onPress = {
                        startHold()
                        try {
                            tryAwaitRelease()
                        } finally {
                            cancelHold()
                        }
                    }
                )
            },
        contentAlignment = Alignment.Center
    ) {
        // No ring on a disabled button: it reads as an active affordance.
        if (isPressed) {
            androidx.wear.compose.material.CircularProgressIndicator(
                progress = holdProgress.value,
                modifier = Modifier.size(WearSecondaryIconButtonHitBoxSize),
                strokeWidth = 3.dp,
                indicatorColor = MaterialTheme.colorScheme.primary,
                trackColor = MediumDarkGray,
            )
        }
        Box(
            modifier = Modifier
                .size(WearSecondaryIconButtonSize)
                .background(buttonBackground, CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                modifier = Modifier.size(WearSecondaryIconButtonIconSize),
                imageVector = icon,
                contentDescription = null,
                tint = Color.White,
            )
        }
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun ControlButtonsVerticalPreview() {
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline,
    ) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            ControlButtonsVertical(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(12.dp),
                onMinusTap = {},
                onMinusLongPress = {},
                onPlusTap = {},
                onPlusLongPress = {},
                onCloseClick = {},
                onResetClick = {},
                isResetEnabled = true,
            ) {
                Text(
                    text = "12",
                    style = MaterialTheme.typography.displayMedium,
                    color = MaterialTheme.colorScheme.onSurface
                )
            }
        }
    }
}
