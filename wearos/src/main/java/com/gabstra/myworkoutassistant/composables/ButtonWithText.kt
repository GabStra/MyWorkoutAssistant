package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.shared.MediumGray

private val PressInteraction.Press.isPressed: Boolean
    get() = true

@Composable
fun ButtonWithText(
    text: String,
    enabled:Boolean = true,
    textColor : Color = MaterialTheme.colors.onBackground,
    backgroundColor: Color = MaterialTheme.colors.background,
    borderColor: Color = MaterialTheme.colors.onBackground,
    onClick: () -> Unit
) {
    val backgroundOnPress = lerp(backgroundColor, textColor, 0.2f)
    val textColorOnPress = lerp(textColor, MaterialTheme.colors.background, 0.2f)

    val disabledColor = MediumGray
    val interactionSource = remember { MutableInteractionSource() }
    val interactions = interactionSource.interactions
    val isPressed = if (enabled) interactions.collectAsState(initial = null).value is PressInteraction.Press else false

    val displayColor = when {
        !enabled -> disabledColor
        isPressed -> textColorOnPress
        else -> textColor
    }

    val borderColorToUse = when {
        !enabled -> disabledColor
        isPressed ->  Color.Transparent
        else -> borderColor
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(50.dp)
            .clip(RoundedCornerShape(50))
            .border(1.dp, borderColorToUse, RoundedCornerShape(50))
            .background(
                when {
                    !enabled -> Color.Transparent
                    isPressed -> backgroundOnPress
                    else -> backgroundColor
                }
            )
            .clickable(
                enabled = enabled,
                interactionSource = interactionSource,
                indication = null,
                onClick = onClick
            )
    ) {
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            ScalableText(
                modifier = Modifier.fillMaxSize(),
                text = text,
                textAlign = TextAlign.Center,
                color = displayColor, // Use the state-aware displayColor
                style = MaterialTheme.typography.title3
            )
        }
    }
}