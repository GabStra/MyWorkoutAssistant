package com.gabstra.myworkoutassistant.composables

import android.widget.Toast
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.util.lerp
import androidx.wear.compose.material.ExperimentalWearMaterialApi
import androidx.wear.compose.material.FractionalThreshold
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.rememberSwipeableState
import androidx.wear.compose.material.swipeable


@OptIn(ExperimentalComposeUiApi::class, ExperimentalFoundationApi::class,
    ExperimentalWearMaterialApi::class
)
@Composable
fun LockScreen(
    show: Boolean = false,
    onUnlock: () -> Unit,
) {
    val state = rememberSwipeableState(initialValue = 0)
    val context = LocalContext.current


    var touchCounter by remember { mutableIntStateOf(0) }

    LaunchedEffect(state.targetValue) {
        if(state.targetValue == 1){
            onUnlock()
        }
    }

    LaunchedEffect(show){
        state.snapTo(0)
    }

    val sizePx = with(LocalDensity.current) { 80.dp.toPx() }
    val anchors = mapOf(0f to 0, -sizePx to 1)

    val swipeProgress = 1- ((sizePx + state.offset.value) / sizePx)
    val animatedOffset by animateDpAsState(targetValue = (-(swipeProgress * sizePx).dp), label = "")
    val animatedScale by animateFloatAsState(targetValue = 1+(swipeProgress*1.05f).coerceAtMost(1.2f), label = "")
    val animatedAlpha by animateFloatAsState(targetValue = lerp(start = 0f, stop = 0.5f, fraction = swipeProgress ), label = "")

    val interactionSource = remember { MutableInteractionSource() }
    if (show) {
        Box(
            modifier = Modifier
                .fillMaxSize()

                .clickable(
                    interactionSource = interactionSource,
                    indication = null
                ) {
                    if(touchCounter>=5){
                        Toast.makeText(context, "Unlock by swiping up", Toast.LENGTH_SHORT).show()
                        touchCounter=0
                    }else{
                        touchCounter++
                    }
                }.swipeable(
                    state = state,
                    anchors = anchors,
                    thresholds = { _, _ -> FractionalThreshold(0.90f) },
                    orientation = Orientation.Vertical
                ),
            contentAlignment = Alignment.TopCenter
        ){
            Icon(
                imageVector = Icons.Filled.Lock,
                contentDescription = "Lock Icon",
                modifier = Modifier
                    .padding(22.dp)
                    .size(15.dp)
            )

            if(swipeProgress>0){
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .size(30.dp)
                        .offset { IntOffset(0, -20+animatedOffset.roundToPx().coerceAtMost(-20)) }
                        .scale(animatedScale)
                        .alpha(animatedAlpha)
                        .background(Color.LightGray, shape = CircleShape)
                )
            }
        }
    }else{
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(22.dp),
            contentAlignment = Alignment.TopCenter
        ){
            Icon(
                imageVector = Icons.Filled.LockOpen,
                contentDescription = "Lock Icon Open",
                modifier = Modifier
                    .size(15.dp)
            )
        }
    }
}