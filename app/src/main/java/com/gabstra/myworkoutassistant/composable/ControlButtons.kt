package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExposureNeg1
import androidx.compose.material.icons.filled.ExposurePlus1
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon

@Composable
fun ControlButtons(
    onMinusClick: () -> Unit,
    onPlusClick: () -> Unit
){
    Row {
        Button(
            onClick = {
                onMinusClick()
            },
            modifier = Modifier.size(35.dp),
            colors = ButtonDefaults.buttonColors(backgroundColor = Color.hsl(9f,0.88f,0.45f))
        ) {
            Icon(imageVector = Icons.Default.ExposureNeg1, contentDescription = "Subtract")
        }
        Spacer(modifier = Modifier.width(10.dp))
        Button(
            onClick = {
                onPlusClick()
            },
            modifier = Modifier.size(35.dp),
            colors = ButtonDefaults.buttonColors(backgroundColor = Color.hsl(113f,0.79f,0.34f))
        ) {
            Icon(imageVector = Icons.Default.ExposurePlus1, contentDescription = "Add")
        }
    }
}