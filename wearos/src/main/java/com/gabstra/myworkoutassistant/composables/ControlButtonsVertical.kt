package com.gabstra.myworkoutassistant.composables

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
    onCloseClick: () -> Unit,
    content: @Composable () -> Unit
){
    val coroutineScope = rememberCoroutineScope()

    BackHandler {
        onCloseClick()
    }

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Box(
            modifier = Modifier
                .size(50.dp)
                .background(Color.Transparent)
                .semantics(mergeDescendants = true) {
                    contentDescription = "Add"
                    role = Role.Button
                    onClick(
                        label = "Add"
                    ) {
                        onPlusTap()
                        true
                    }
                    onLongClick(
                        label = "Add"
                    ) {
                        onPlusLongPress()
                        true
                    }
                }
                .repeatActionOnLongPressOrTap(
                    coroutineScope,
                    thresholdMillis = 1000,
                    intervalMillis = 150,
                    onAction = onPlusLongPress,
                    onTap = onPlusTap
                ),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .size(50.dp)
                    .subtleVerticalGradientBackground(Green,CircleShape),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    modifier = Modifier.size(30.dp),
                    imageVector = Icons.Filled.ArrowUpward,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onBackground
                )
            }
        }

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 2.5.dp),
            contentAlignment = Alignment.Center
        ) {
            content()
        }

        Box(
            modifier = Modifier
                .size(50.dp)
                .background(Color.Transparent)
                .semantics(mergeDescendants = true) {
                    contentDescription = "Subtract"
                    role = Role.Button
                    onClick(
                        label = "Subtract"
                    ) {
                        onMinusTap()
                        true
                    }
                    onLongClick(
                        label = "Subtract"
                    ) {
                        onMinusLongPress()
                        true
                    }
                }
                .repeatActionOnLongPressOrTap(
                    coroutineScope,
                    thresholdMillis = 1000,
                    intervalMillis = 150,
                    onAction = onMinusLongPress,
                    onTap = onMinusTap
                ),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .size(50.dp)
                    .subtleVerticalGradientBackground(Red,CircleShape),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    modifier = Modifier.size(30.dp),
                    imageVector = Icons.Filled.ArrowDownward,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onBackground
                )
            }
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
