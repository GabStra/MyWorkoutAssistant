package com.gabstra.myworkoutassistant.composables

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
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
import com.gabstra.myworkoutassistant.data.repeatActionOnLongPressOrTap
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red

internal const val WEAR_CONTROL_EDIT_INACTIVITY_TIMEOUT_MILLIS = 10_000L

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

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(20.dp, Alignment.CenterHorizontally),
            ) {
                ControlButton(Icons.Filled.ArrowDownward, "Subtract", Red, isMinusEnabled, onMinusTap, onMinusLongPress)
                ControlButton(Icons.Filled.ArrowUpward, "Add", Green, isPlusEnabled, onPlusTap, onPlusLongPress)
            }
            if (onCloseClick != null || onResetClick != null) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterHorizontally),
                ) {
                    onCloseClick?.let { closeClick ->
                        ControlButton(
                            Icons.AutoMirrored.Filled.ArrowBack, "Back",
                            MaterialTheme.colorScheme.surfaceContainerHigh, true,
                            closeClick, closeClick, 48.dp, 40.dp, 20.dp,
                        )
                    }
                    onResetClick?.let { resetClick ->
                        ControlButton(
                            Icons.Filled.RestartAlt, "Reset",
                            MaterialTheme.colorScheme.surfaceContainerHigh, isResetEnabled,
                            resetClick, resetClick, 48.dp, 40.dp, 20.dp,
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
    hitBoxSize: androidx.compose.ui.unit.Dp = WearStandardIconButtonHitBoxSize,
    buttonSize: androidx.compose.ui.unit.Dp = WearStandardIconButtonSize,
    iconSize: androidx.compose.ui.unit.Dp = WearStandardIconButtonIconSize,
) {
    Box(
        modifier = Modifier
            .size(hitBoxSize)
            .alpha(if (enabled) 1f else 0.45f)
            .semantics(mergeDescendants = true) {
                this.contentDescription = contentDescription
                role = Role.Button
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
                thresholdMillis = 1000,
                intervalMillis = 150,
                enabled = enabled,
                onAction = onLongPress,
                onTap = onTap
            ),
        contentAlignment = Alignment.Center
    ) {
        Box(
            modifier = Modifier
                .size(buttonSize)
                .background(backgroundColor, CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                modifier = Modifier.size(iconSize),
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onBackground,
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
