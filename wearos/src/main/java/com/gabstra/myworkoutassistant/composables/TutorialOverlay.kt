package com.gabstra.myworkoutassistant.composables

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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar

/**
 * Simple dimmed overlay used as a lightweight "coach-mark" style tutorial.
 *
 * This is intentionally generic so it can be reused on multiple screens.
 */
@Composable
fun TutorialOverlay(
    visible: Boolean,
    text: String,
    modifier: Modifier = Modifier,
    onDismiss: () -> Unit,
    buttonText: String = "Got it"
) {
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
            ScreenScaffold(
                modifier = Modifier.fillMaxSize()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(25.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    val scrollState = rememberScrollState()
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxWidth()
                            .verticalColumnScrollbar(
                                scrollState = scrollState,
                                scrollBarColor = MaterialTheme.colorScheme.onBackground
                            )
                            .verticalScroll(scrollState),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = text,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onBackground,
                            textAlign = TextAlign.Center
                        )
                    }

                    // Fixed button at the bottom
                    Box(
                        modifier = Modifier
                            .fillMaxWidth(),
                        contentAlignment = Alignment.Center
                    ) {
                        Button(
                            onClick = onDismiss,
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 5.dp)
                        ) {
                            Text(
                                text = buttonText,
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Center
                            )
                        }
                    }
                }
            }
        }
    }
}

