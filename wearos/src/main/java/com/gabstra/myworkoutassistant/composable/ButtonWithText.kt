package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.getContrastRatio

@Composable
fun ButtonWithText(text: String, enabled:Boolean = true, backgroundColor: Color = MaterialTheme.colors. primary, onClick: () -> Unit) {
    val textColor = if (getContrastRatio(backgroundColor, Color.Black) > getContrastRatio(backgroundColor, Color.White)) {
        Color.Black
    } else {
        Color.White
    }

    Button(
        onClick,
        modifier = Modifier
            .fillMaxWidth()
            .padding(5.dp),
        colors = ButtonDefaults.buttonColors(backgroundColor),
        enabled = enabled
    ) {
        Row(
            modifier = Modifier.fillMaxSize().padding(vertical = 5.dp, horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            Text(
                text = text,
                textAlign = TextAlign.Center,
                color = textColor,
                style = MaterialTheme.typography.title3
            )
        }

    }
}