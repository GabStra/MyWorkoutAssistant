package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DisabledContentGray

@Composable
fun CustomButton(
    modifier: Modifier = Modifier,
    text: String,
    textColor: Color = MaterialTheme.colorScheme.onBackground,
    onClick: () -> Unit,
    backgroundColor: Color = MaterialTheme.colorScheme.surfaceVariant,
    enabled: Boolean = true
) {
    val backgroundOnPress = lerp(backgroundColor, textColor, 0.2f)
    val textColorOnPress = lerp(textColor, MaterialTheme.colorScheme.background, 0.2f)

    val disabledColor = DisabledContentGray
    val interactionSource = remember { MutableInteractionSource() }
    val interactions = interactionSource.interactions
    val isPressed = if (enabled) interactions.collectAsState(initial = null).value is PressInteraction.Press else false

    val displayColor = when {
        !enabled -> disabledColor
        isPressed -> textColorOnPress
        else -> textColor
    }

    Box(
        modifier = modifier
            .heightIn(min = 48.dp)
            .clip(RoundedCornerShape(50))
            .background(
                when {
                    !enabled -> MaterialTheme.colorScheme.scrim
                    isPressed -> backgroundOnPress
                    else -> backgroundColor
                }
            )
            .clickable(
                enabled = enabled,
                interactionSource = interactionSource,
                indication = null,
                onClick = onClick
            ),
        contentAlignment = Alignment.Center
    ) {
        Text(
            modifier = Modifier.padding(horizontal = 17.5.dp),
            text = text,
            color = displayColor,
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.bodyLarge
        )
    }
}

