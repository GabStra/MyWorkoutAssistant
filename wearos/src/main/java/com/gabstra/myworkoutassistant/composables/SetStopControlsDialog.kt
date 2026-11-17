package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Stop
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onLongClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.foundation.shape.CircleShape
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.Red
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

// Label-free hold target: bigger than the standard button since it is the primary hold action.
private val HoldToStopButtonSize = 60.dp

@Composable
internal fun SetStopControlsDialog(onStop: () -> Unit, onDismiss: () -> Unit) {
    val holdDurationMillis = LocalViewConfiguration.current.longPressTimeoutMillis.toInt()
    val latestOnStop by rememberUpdatedState(onStop)
    val holdProgress = remember { Animatable(0f) }
    var isStopPressed by remember { mutableStateOf(false) }
    val stopButtonColor by animateColorAsState(
        targetValue = if (isStopPressed) darkenButtonColor(Red) else Red,
        label = "stop button press",
    )
    val stopIconColor by animateColorAsState(
        targetValue = if (isStopPressed) darkenButtonColor(Color.White)
        else Color.White,
        label = "stop icon press",
    )
    val titleText = stringResource(R.string.set_controls_title)
    val holdToStopDescription = stringResource(R.string.set_controls_cd_hold_to_stop)
    val stopSetLabel = stringResource(R.string.set_controls_action_stop)
    val backDescription = stringResource(R.string.set_controls_cd_back)
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            dismissOnBackPress = true,
            dismissOnClickOutside = false,
            usePlatformDefaultWidth = false,
        ),
    ) {
        Box(
            modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                modifier = Modifier.fillMaxSize().padding(horizontal = 24.dp, vertical = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.SpaceEvenly,
            ) {
                Text(titleText, style = MaterialTheme.typography.titleMedium)
                Box(
                    modifier = Modifier
                        .size(HoldToStopButtonSize)
                    .semantics {
                        role = Role.Button
                        contentDescription = holdToStopDescription
                        onLongClick(label = stopSetLabel) {
                            latestOnStop()
                            true
                        }
                    }
                    .pointerInput(holdDurationMillis) {
                        detectTapGestures(onPress = {
                            val pressScope = this
                            isStopPressed = true
                            coroutineScope {
                                val holdJob = launch {
                                    holdProgress.snapTo(0f)
                                    holdProgress.animateTo(
                                        targetValue = 1f,
                                        animationSpec = tween(holdDurationMillis, easing = LinearEasing),
                                    )
                                    latestOnStop()
                                }
                                try {
                                    pressScope.tryAwaitRelease()
                                } finally {
                                    isStopPressed = false
                                    holdJob.cancel()
                                    holdProgress.snapTo(0f)
                                }
                            }
                        })
                    },
                contentAlignment = Alignment.Center,
            ) {
                if (holdProgress.value > 0f) {
                    androidx.wear.compose.material.CircularProgressIndicator(
                        progress = holdProgress.value,
                        modifier = Modifier.size(HoldToStopButtonSize),
                        strokeWidth = 4.dp,
                        indicatorColor = Red,
                        trackColor = MediumDarkGray,
                    )
                }
                Box(
                    modifier = Modifier
                        .size(HoldToStopButtonSize)
                        .clip(CircleShape)
                        .background(stopButtonColor),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        modifier = Modifier.size(wearIconSizeForButton(HoldToStopButtonSize)),
                        imageVector = Icons.Default.Stop,
                        contentDescription = null,
                        tint = stopIconColor,
                    )
                }
            }
            EnhancedIconButton(
                onClick = onDismiss,
                buttonSize = WearStandardIconButtonSize,
                hitBoxScale = 1.2f,
                colors = wearColoredIconButtonColors(MaterialTheme.colorScheme.surfaceContainerHigh),
                buttonModifier = Modifier.clip(CircleShape),
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = backDescription,
                    tint = androidx.wear.compose.material3.LocalContentColor.current,
                )
            }
            }
        }
    }
}
