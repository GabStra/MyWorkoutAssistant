package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.ui.theme.MediumDarkGray
import com.gabstra.myworkoutassistant.ui.theme.MediumLightGray
import com.kevinnzou.compose.progressindicator.SimpleProgressIndicator

@Composable
fun CheckboxWithGreenCircle(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .size(40.dp) // Circle size
            .clip(CircleShape) // Clip the box to a circle shape
            .background(Color(0xFFff6700)),

    ) {
        Icon(
            imageVector = Icons.Default.Check,
            contentDescription = "Checkbox",
            tint = Color.DarkGray, // Icon color
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
            .fillMaxWidth() // Make the progress bar fill the width of its parent
    ) {
        SimpleProgressIndicator(
            progress = progress,
            trackColor = MediumDarkGray,
            progressBarColor =  Color(0xFFff6700),
            modifier = Modifier
                .fillMaxWidth()
                .height(16.dp)
                .clip(roundedCornerShape) // Clip the progress bar to the rounded shape
        )
    }
}

@Composable
fun ObjectiveProgressBar(modifier: Modifier=Modifier,progress: Float){
    Box(
        modifier = modifier // Padding around the Box
    ) {
        LinearProgressBarWithRounderBorders(
            progress = progress,
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.CenterStart)
        )
        val isFilled = progress >= 1f
        if(isFilled){
            CheckboxWithGreenCircle(modifier = Modifier.align(Alignment.CenterEnd))
        }
    }
}