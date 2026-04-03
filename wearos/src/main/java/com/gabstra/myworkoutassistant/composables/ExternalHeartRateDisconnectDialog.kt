package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.Red

@Composable
fun ExternalHeartRateDisconnectDialog(
    show: Boolean,
    title: String,
    message: String,
    onRetry: () -> Unit,
    onContinueWithoutSensor: () -> Unit,
    onEndWorkout: () -> Unit,
    onVisibilityChange: (Boolean) -> Unit = {},
) {
    LaunchedEffect(show) {
        onVisibilityChange(show)
    }

    if (!show) return

    Dialog(
        onDismissRequest = {},
        properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false)
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.65f))
        ) {
            val scrollState = rememberScrollState()
            ScreenScaffold(
                modifier = Modifier.fillMaxSize(),
                scrollState = scrollState,
                overscrollEffect = null,
                scrollIndicator = {
                    ScrollIndicator(
                        state = scrollState,
                        colors = ScrollIndicatorDefaults.colors(
                            indicatorColor = MaterialTheme.colorScheme.onBackground,
                            trackColor = MediumDarkGray
                        )
                    )
                }
            ) { contentPadding ->
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(
                            PaddingValues(
                                start = contentPadding.calculateLeftPadding(LayoutDirection.Rtl),
                                end = contentPadding.calculateRightPadding(LayoutDirection.Rtl)
                            )
                        )
                        .verticalScroll(scrollState),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(14.dp)
                            .background(
                                color = MaterialTheme.colorScheme.background,
                                shape = RoundedCornerShape(18.dp)
                            )
                            .padding(14.dp),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = title,
                            style = MaterialTheme.typography.titleMedium,
                            textAlign = TextAlign.Center
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = message,
                            style = MaterialTheme.typography.bodySmall,
                            textAlign = TextAlign.Center
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                        WearPrimaryButton(
                            modifier = Modifier.fillMaxWidth(),
                            text = "Retry",
                            onClick = onRetry
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        ButtonWithText(
                            modifier = Modifier.fillMaxWidth(),
                            text = "Continue",
                            onClick = onContinueWithoutSensor
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButtonWithText(
                            modifier = Modifier.fillMaxWidth(),
                            text = "End workout",
                            borderColor = Red,
                            textColor = Red,
                            onClick = onEndWorkout
                        )
                    }
                }
            }
        }
    }
}
