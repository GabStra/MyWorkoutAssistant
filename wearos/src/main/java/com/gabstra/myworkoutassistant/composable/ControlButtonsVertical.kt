package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.ui.Alignment

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Check
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.data.repeatActionOnLongPress
import com.gabstra.myworkoutassistant.data.repeatActionOnLongPressOrTap
import com.gabstra.myworkoutassistant.presentation.theme.MyColors


@Composable
fun ControlButtonsVertical(
    modifier: Modifier,
    onMinusTap: () -> Unit,
    onMinusLongPress: () -> Unit,
    onPlusTap: () -> Unit,
    onPlusLongPress: () -> Unit,
    content: @Composable () -> Unit
){
    val coroutineScope = rememberCoroutineScope()

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Box(
            modifier = Modifier
                .size(70.dp, 35.dp)
                .background(Color.Transparent)
                .repeatActionOnLongPressOrTap(
                    coroutineScope,
                    thresholdMillis = 1000,
                    intervalMillis = 150,
                    onAction = onPlusLongPress,
                    onTap = onPlusTap
                ),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .size(35.dp)
                    .clip(CircleShape)
                    .background(MyColors.Green),
                contentAlignment = Alignment.Center
            ) {
                Icon(imageVector = Icons.Filled.ArrowUpward, contentDescription = "Add")
            }
        }
        Box(
            modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
            contentAlignment = Alignment.Center
        ) {
            content()
        }
        Box(
            modifier = Modifier
                .size(70.dp, 35.dp)
                .background(Color.Transparent)
                .repeatActionOnLongPressOrTap(
                    coroutineScope,
                    thresholdMillis = 1000,
                    intervalMillis = 150,
                    onAction = onMinusLongPress,
                    onTap = onMinusTap
                ),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .size(35.dp)
                    .clip(CircleShape)
                    .background(MyColors.Red),
                contentAlignment = Alignment.Center
            ) {
                Icon(imageVector = Icons.Filled.ArrowDownward, contentDescription = "Subtract")
            }
        }

    }
}