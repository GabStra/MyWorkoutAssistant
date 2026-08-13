package com.gabstra.myworkoutassistant.workout

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import com.gabstra.myworkoutassistant.repeatActionOnLongPressOrTap
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red

internal const val CONTROL_EDIT_INACTIVITY_TIMEOUT_MILLIS = 10_000L
internal const val TIMER_EDIT_INCREMENT_MILLIS = 2_500
internal val SET_VALUE_HORIZONTAL_SPACING = 36.dp

private val ControlButtonHitBoxSize = 88.dp
private val ControlButtonSize = 72.dp
private val ControlButtonIconSize = 36.dp
private val SecondaryControlButtonHitBoxSize = 64.dp
private val SecondaryControlButtonSize = 56.dp
private val SecondaryControlButtonIconSize = 28.dp

@Composable
fun SetValueSection(
    label: String,
    headerStyle: TextStyle,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(2.5.dp),
    ) {
        Text(
            text = label,
            style = headerStyle,
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center,
        )
        content()
    }
}

@Composable
fun TargetRepRangeLabel(targetRepRange: String) {
    Text(
        text = "TARGET REPS: $targetRepRange",
        style = MaterialTheme.typography.bodyLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
        maxLines = 1,
    )
}

@Composable
fun ControlButtonsVertical(
    modifier: Modifier,
    onMinusTap: () -> Unit,
    onMinusLongPress: () -> Unit,
    onPlusTap: () -> Unit,
    onPlusLongPress: () -> Unit,
    isMinusEnabled: Boolean = true,
    isPlusEnabled: Boolean = true,
    isResetEnabled: Boolean = true,
    onCloseClick: (() -> Unit)? = null,
    onResetClick: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    BackHandler(enabled = onCloseClick != null) {
        onCloseClick?.invoke()
    }

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .padding(horizontal = 12.dp),
            contentAlignment = Alignment.Center,
        ) {
            content()
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(28.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(40.dp, Alignment.CenterHorizontally),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ControlButton(
                    icon = Icons.Filled.ArrowDownward,
                    contentDescription = "Subtract",
                    backgroundColor = Red,
                    enabled = isMinusEnabled,
                    onTap = onMinusTap,
                    onLongPress = onMinusLongPress,
                )
                ControlButton(
                    icon = Icons.Filled.ArrowUpward,
                    contentDescription = "Add",
                    backgroundColor = Green,
                    enabled = isPlusEnabled,
                    onTap = onPlusTap,
                    onLongPress = onPlusLongPress,
                )
            }

            if (onCloseClick != null || onResetClick != null) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(32.dp, Alignment.CenterHorizontally),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    onCloseClick?.let { closeClick ->
                        ControlButton(
                            icon = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                            backgroundColor = MaterialTheme.colorScheme.surfaceVariant,
                            enabled = true,
                            hitBoxSize = SecondaryControlButtonHitBoxSize,
                            buttonSize = SecondaryControlButtonSize,
                            iconSize = SecondaryControlButtonIconSize,
                            onTap = closeClick,
                            onLongPress = closeClick,
                        )
                    }
                    onResetClick?.let { resetClick ->
                        ControlButton(
                            icon = Icons.Filled.RestartAlt,
                            contentDescription = "Reset",
                            backgroundColor = MaterialTheme.colorScheme.surfaceVariant,
                            enabled = isResetEnabled,
                            hitBoxSize = SecondaryControlButtonHitBoxSize,
                            buttonSize = SecondaryControlButtonSize,
                            iconSize = SecondaryControlButtonIconSize,
                            onTap = { if (isResetEnabled) resetClick() },
                            onLongPress = { if (isResetEnabled) resetClick() },
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
    hitBoxSize: androidx.compose.ui.unit.Dp = ControlButtonHitBoxSize,
    buttonSize: androidx.compose.ui.unit.Dp = ControlButtonSize,
    iconSize: androidx.compose.ui.unit.Dp = ControlButtonIconSize,
    onTap: () -> Unit,
    onLongPress: () -> Unit,
) {
    val coroutineScope = rememberCoroutineScope()
    Box(
        modifier = Modifier
            .size(hitBoxSize)
            .alpha(if (enabled) 1f else 0.45f)
            .repeatActionOnLongPressOrTap(
                coroutineScope = coroutineScope,
                thresholdMillis = 1000,
                intervalMillis = 150,
                onAction = { if (enabled) onLongPress() },
                onTap = { if (enabled) onTap() },
            ),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(buttonSize)
                .background(backgroundColor, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                modifier = Modifier.size(iconSize),
                imageVector = icon,
                contentDescription = contentDescription,
                tint = MaterialTheme.colorScheme.onBackground,
            )
        }
    }
}
