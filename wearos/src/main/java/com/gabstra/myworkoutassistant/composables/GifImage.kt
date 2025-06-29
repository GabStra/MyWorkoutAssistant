package com.gabstra.myworkoutassistant.composables

import androidx.annotation.DrawableRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext

@Composable
fun GifImage(
    modifier: Modifier = Modifier,
    @DrawableRes imageRes: Int,
) {
    val context = LocalContext.current
    /*val imageLoader = remember {
        ImageLoader.Builder(context)
            .components {
                add(ImageDecoderDecoder.Factory())
            }
            .build()
    }

    Image(
        painter = rememberAsyncImagePainter(model = imageRes, imageLoader = imageLoader),
        contentDescription = null,
        modifier = modifier,
    )*/
}