package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray

/** A single tutorial step with a title and description. */
data class TutorialStep(val title: String, val description: String)

@Composable
private fun TutorialStepItem(
    title: String,
    description: String,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        Text(
            text = title,
            modifier = Modifier.fillMaxWidth(),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = LighterGray,
            textAlign = TextAlign.Center
        )
        if (description.isNotEmpty()) {
            Text(
                text = description,
                modifier = Modifier.padding(top = 4.dp),
                style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Normal),
                color = MediumLighterGray,
                textAlign = TextAlign.Center
            )
        }
    }
}

/**
 * Simple dimmed overlay used as a lightweight "coach-mark" style tutorial.
 *
 * This is intentionally generic so it can be reused on multiple screens.
 * Each step is shown as a stacked item with title in bold and description in regular text.
 */
@Composable
fun TutorialOverlay(
    visible: Boolean,
    steps: List<TutorialStep>,
    modifier: Modifier = Modifier,
    onDismiss: () -> Unit,
    buttonText: String = "Got it",
    hapticsViewModel: HapticsViewModel? = null,
    onVisibilityChange: (Boolean) -> Unit = {}
) {
    LaunchedEffect(visible) {
        onVisibilityChange(visible)
    }

    AnimatedVisibility(
        visible = visible,
        enter = fadeIn(),
        exit = fadeOut()
    ) {
        Box(
            modifier = modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background),
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
                        .padding(
                            PaddingValues(
                                start = contentPadding.calculateLeftPadding(LayoutDirection.Rtl),
                                end = contentPadding.calculateRightPadding( LayoutDirection.Rtl)
                            )
                        )
                        .verticalScroll(scrollState),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 20.dp)
                            .padding(horizontal = 25.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        steps.forEach { step ->
                            TutorialStepItem(
                                title = step.title,
                                description = step.description,
                                modifier = Modifier.fillMaxWidth()
                            )
                        }
                    }

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
