package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.MediumGray

@Composable
fun CustomOutlinedButton(
    text: String,
    color: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    val backgroundOnPress = color.copy(alpha = 0.15f)
    val disabledColor = MediumGray
    val interactionSource = remember { MutableInteractionSource() }
    val interactions = interactionSource.interactions
    val isPressed = if (enabled) interactions.collectAsState(initial = null).value is PressInteraction.Press else false

    val displayColor = if (enabled) color else disabledColor

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(50))
            .border(1.dp, displayColor, RoundedCornerShape(50))
            .background(
                when {
                    !enabled -> Color.Transparent
                    isPressed -> backgroundOnPress
                    else -> Color.Transparent
                }
            )
            .clickable(
                enabled = enabled,
                interactionSource = interactionSource,
                indication = ripple(
                    bounded = true,
                    color = displayColor
                ),
                onClick = onClick
            )
            .padding(horizontal = 24.dp, vertical = 8.dp)
    ) {
        Text(
            text = text,
            color = displayColor,
            textAlign = TextAlign.Center,
            modifier = Modifier.align(Alignment.Center)
        )
    }
}