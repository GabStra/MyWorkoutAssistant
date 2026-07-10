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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
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


@Composable
fun ControlButtonsVertical(
    modifier: Modifier,
    onMinusTap: () -> Unit,
    onMinusLongPress: () -> Unit,
    onPlusTap: () -> Unit,
    onPlusLongPress: () -> Unit,
    isMinusEnabled: Boolean = true,
    isPlusEnabled: Boolean = true,
    onCloseClick: () -> Unit,
    content: @Composable () -> Unit
){
    BackHandler {
        onCloseClick()
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
                .padding(horizontal = 30.dp),
            contentAlignment = Alignment.Center
        ) {
            content()
        }

        Row(
            horizontalArrangement = Arrangement.Center,
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 22.5.dp)
        ) {
            ControlButton(
                contentDescription = "Subtract",
                icon = {
                    Icon(
                        modifier = Modifier.size(WearStandardIconButtonIconSize),
                        imageVector = Icons.Filled.ArrowDownward,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onBackground
                    )
                },
                backgroundColor = Red,
                enabled = isMinusEnabled,
                onTap = onMinusTap,
                onLongPress = onMinusLongPress
            )
            Spacer(modifier = Modifier.width(15.dp))
            ControlButton(
                contentDescription = "Add",
                icon = {
                    Icon(
                        modifier = Modifier.size(WearStandardIconButtonIconSize),
                        imageVector = Icons.Filled.ArrowUpward,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onBackground
                    )
                },
                backgroundColor = Green,
                enabled = isPlusEnabled,
                onTap = onPlusTap,
                onLongPress = onPlusLongPress
            )
        }
    }
}

@Composable
private fun ControlButton(
    contentDescription: String,
    icon: @Composable () -> Unit,
    backgroundColor: Color,
    enabled: Boolean,
    onTap: () -> Unit,
    onLongPress: () -> Unit
) {
    Box(
        modifier = Modifier
            .size(WearStandardIconButtonHitBoxSize)
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
                .size(WearStandardIconButtonSize)
                .background(backgroundColor, CircleShape),
            contentAlignment = Alignment.Center
        ) {
            icon()
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
