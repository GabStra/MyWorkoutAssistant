// ButtonWithText.kt
package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.AppFilledTonalButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton

enum class AppButtonStyle { Filled, Tonal, Outlined }

@Composable
fun ButtonWithText(
    modifier: Modifier = Modifier,
    text: String,
    enabled: Boolean = true,
    onClick: () -> Unit,
    style: AppButtonStyle = AppButtonStyle.Filled
) {
    val baseModifier = modifier
        .fillMaxWidth()
        // Ensure min 48.dp touch target (M3 recommendation)
        .minimumInteractiveComponentSize()
        .heightIn(min = 48.dp)

    when (style) {
        AppButtonStyle.Filled -> AppPrimaryButton(
            modifier = baseModifier,
            text = text,
            onClick = onClick,
            enabled = enabled,
            textAlign = TextAlign.Center
        )
        AppButtonStyle.Tonal -> AppFilledTonalButton(
            modifier = baseModifier,
            text = text,
            onClick = onClick,
            enabled = enabled,
            textAlign = TextAlign.Center
        )
        AppButtonStyle.Outlined -> AppPrimaryOutlinedButton(
            modifier = baseModifier,
            text = text,
            onClick = onClick,
            enabled = enabled,
            textAlign = TextAlign.Center
        )
    }
}
