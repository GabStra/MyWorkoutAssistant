package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.shared.MediumDarkGray

data class LoadedPlateConfigurationOption(
    val plates: List<Double>,
    val label: String,
    val isCurrent: Boolean,
)

@Composable
fun LoadedPlateConfigurationPickerOverlay(
    show: Boolean,
    options: List<LoadedPlateConfigurationOption>,
    onSelect: (List<Double>) -> Unit,
    onDismiss: () -> Unit,
) {
    if (!show) return

    val scrollState = rememberTransformingLazyColumnState()
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            dismissOnBackPress = true,
            dismissOnClickOutside = false,
        ),
    ) {
        ScreenScaffold(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background),
            scrollState = scrollState,
            scrollIndicator = {
                ScrollIndicator(
                    state = scrollState,
                    colors = ScrollIndicatorDefaults.colors(
                        indicatorColor = MaterialTheme.colorScheme.onBackground,
                        trackColor = MediumDarkGray,
                    ),
                )
            },
        ) { _ ->
            TransformingLazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 20.dp),
                contentPadding = WorkoutPagerPageSafeAreaPadding,
                state = scrollState,
            ) {
                item {
                    Text(
                        text = "What is loaded?",
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 6.dp, bottom = 10.dp),
                    )
                }
                items(options.size) { index ->
                    val option = options[index]
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 56.dp),
                        text = if (option.isCurrent) {
                            "${option.label} (Current)"
                        } else {
                            option.label
                        },
                        enabled = !option.isCurrent,
                        onClick = { onSelect(option.plates) },
                    )
                }
                item {
                    CancelButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 56.dp),
                        text = "Cancel",
                        onClick = onDismiss,
                    )
                }
            }
        }
    }
}
