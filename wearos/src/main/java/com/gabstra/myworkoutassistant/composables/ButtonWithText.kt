package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumGray

@Composable
fun ButtonWithText(
    text: String,
    enabled:Boolean = true,
    textColor : Color = MaterialTheme.colors.onBackground,
    backgroundColor: Color = MediumDarkGray,
    style: TextStyle = MaterialTheme.typography.body1,
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

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 50.dp)
            .clip(RoundedCornerShape(50))
            .background(
                when {
                    !enabled -> DarkGray
                    isPressed -> backgroundOnPress
                    else -> backgroundColor
                }
            )
            .clickable(
                enabled = enabled
            ){
                onClick()
            },
        contentAlignment = Alignment.Center
    ) {
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = text,
                textAlign = TextAlign.Center,
                color = displayColor,
                style = style
            )
        }
    }
}