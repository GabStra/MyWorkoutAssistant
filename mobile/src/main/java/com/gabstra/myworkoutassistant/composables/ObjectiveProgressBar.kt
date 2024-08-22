package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.dp

@Composable
fun CheckboxWithGreenCircle(modifier: Modifier = Modifier){
    Box(
        modifier = modifier
            .size(40.dp) // Circle size
            .clip(CircleShape) // Clip the box to a circle shape
            .background(Color(0xFFff6700)) // Green background

    ) {
        Icon(
            imageVector = Icons.Default.Check,
            contentDescription = "Checkbox",
            tint = Color.White, // Icon color
            modifier = Modifier.align(Alignment.Center) // Center the icon within the circle
        )
    }
}

@Composable
fun LinearProgressBarWithRounderBorders(progress: Float, modifier: Modifier = Modifier){
    val roundedCornerShape: Shape = RoundedCornerShape(16.dp)

    Box(
        modifier = modifier // Padding around the entire progress bar
            .clip(roundedCornerShape) // Clip the box to have rounded corners
            .border(
                width = 3.dp, // Border width
                color = Color(0xFFff6700), // Border color
                shape = roundedCornerShape // Apply the same shape to the border
            )

            .fillMaxWidth() // Make the progress bar fill the width of its parent
    ) {
        LinearProgressIndicator(
            progress = { progress },
            trackColor = Color.DarkGray,
            color =  Color(0xFFff6700),
            modifier = Modifier
                .fillMaxWidth()
                .height(16.dp)
                .clip(roundedCornerShape) // Clip the progress bar to the rounded shape
                .background(Color.White), // Background color inside the border
        )
    }
}

@Composable
fun ObjectiveProgressBar(modifier: Modifier=Modifier,progress: Float){
    Box(
        modifier = modifier // Padding around the Box
    ) {
        // Progress bar filling 80% width of the Box
        LinearProgressBarWithRounderBorders(
            progress = progress,
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.CenterStart)
        )

        CheckboxWithGreenCircle(modifier = Modifier.align(Alignment.CenterEnd))
    }
}