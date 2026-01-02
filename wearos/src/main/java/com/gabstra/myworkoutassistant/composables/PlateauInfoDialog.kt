package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.MediumDarkGray

@Composable
fun PlateauInfoDialog(
    show: Boolean,
    reason: String,
    onDismiss: () -> Unit,
    hapticsViewModel: HapticsViewModel? = null,
    buttonText: String = "Got it",
    onVisibilityChange: (Boolean) -> Unit = {}
) {
    LaunchedEffect(show) {
        onVisibilityChange(show)
    }

    if (show) {
        Dialog(
            onDismissRequest = onDismiss,
            properties = DialogProperties(
                dismissOnBackPress = true,
                dismissOnClickOutside = false,
                usePlatformDefaultWidth = false
            )
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black),
                contentAlignment = Alignment.Center
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
                            .padding(contentPadding)
                            .padding(horizontal = 16.dp, vertical = 12.dp)
                            .verticalScroll(scrollState),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = "Plateau Detection Details",
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp),
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onBackground,
                            textAlign = TextAlign.Center
                        )

                        Text(
                            text = reason,
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onBackground,
                            textAlign = TextAlign.Center
                        )

                        // Button now scrolls with the text
                        Button(
                            onClick = {
                                hapticsViewModel?.doGentleVibration()
                                onDismiss()
                            },
                        ) {
                            Text(
                                text = buttonText,
                                style = MaterialTheme.typography.bodyLarge,
                                textAlign = TextAlign.Center,
                                color = MaterialTheme.colorScheme.onPrimary
                            )
                        }
                    }
                }
            }
        }
    }
}

