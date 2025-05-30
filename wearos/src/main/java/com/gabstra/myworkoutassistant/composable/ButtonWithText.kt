package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.presentation.theme.MyColors

@Composable
fun ButtonWithText(
    text: String, enabled:Boolean = true,
    backgroundColor: Color = MaterialTheme.colors.background,
    onClick: () -> Unit
) {
    val textColor = MyColors.White

    Button(
        onClick,
        modifier = Modifier
            .fillMaxWidth(),
        colors = ButtonDefaults.buttonColors(backgroundColor),
        enabled = enabled
    ) {
        Row(
            modifier = Modifier.fillMaxSize().padding(5.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            ScalableText(
                modifier = Modifier.fillMaxSize(),
                text = text,
                textAlign = TextAlign.Center,
                color = textColor,
                style = MaterialTheme.typography.title3
            )
        }
    }
}