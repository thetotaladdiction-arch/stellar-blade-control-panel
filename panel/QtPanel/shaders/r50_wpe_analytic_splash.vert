#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;
layout(location = 1) out vec2 qt_SceneCoord;

// Keep this block byte-for-byte identical to the fragment stage. Qt Quick
// shares binding 0 between both stages on every RHI backend.
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float age;
    float lifetime;
    float strength;
    float eventSeed;
    float roleCode;
    vec2 splashCenter;
    vec2 splashExtent;
    vec2 viewportSize;
    float sceneTime;
    float waterRippleSpeed;
    vec4 jet0;
    vec4 jet1;
    vec4 jet2;
    vec4 jet3;
    vec4 jet4;
    vec4 jet5;
    vec4 jet6;
} ubuf;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;
    qt_SceneCoord = ubuf.splashCenter
                  + (qt_MultiTexCoord0 - vec2(0.5, 0.72))
                  * ubuf.splashExtent;
    gl_Position = ubuf.qt_Matrix * qt_Vertex;
}
