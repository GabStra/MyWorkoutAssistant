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

data class SupersetStartMemberOption(
    val memberIndex: Int,
    val name: String,
    val isCurrent: Boolean
)

/**
 * Rotating EMOM: pick the movement the rotation starts from, or build the full
 * member order one position at a time.
 */
@Composable
fun SupersetStartMemberPickerOverlay(
    show: Boolean,
    title: String,
    options: List<SupersetStartMemberOption>,
    onSelect: (Int) -> Unit,
    onDismiss: () -> Unit
) {
    if (!show) return

    val scrollState = rememberTransformingLazyColumnState()

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(dismissOnBackPress = true, dismissOnClickOutside = false)
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
                        trackColor = MediumDarkGray
                    )
                )
            }
        ) { contentPadding ->
            TransformingLazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top = contentPadding.calculateTopPadding())
                    .padding(horizontal = 10.dp),
                state = scrollState
            ) {
                item {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 6.dp, bottom = 4.dp)
                    )
                }
                item {
                    Text(
                        text = "One movement per slot, rotating in this order",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(bottom = 10.dp)
                    )
                }
                items(options.size) { index ->
                    val option = options[index]
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 56.dp),
                        text = if (option.isCurrent) "${option.name} (Current)" else option.name,
                        enabled = !option.isCurrent,
                        onClick = { onSelect(option.memberIndex) }
                    )
                }
                item {
                    CancelButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 56.dp),
                        text = "Cancel",
                        onClick = onDismiss
                    )
                }
            }
        }
    }
}
