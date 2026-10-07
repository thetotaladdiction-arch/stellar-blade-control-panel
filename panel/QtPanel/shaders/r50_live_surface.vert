#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float wetIntensity;
    float surfaceAspect;
    vec2 viewportSize;
    float rippleDisplacementPixels;
    vec4 ripple0;
    vec4 ripple1;
    vec4 ripple2;
    vec4 ripple3;
    vec4 ripple4;
    vec4 ripple5;
    vec4 ripple6;
    vec4 ripple7;
    vec4 lens0;
    vec4 lens1;
    vec4 lens2;
    vec4 lens3;
    vec4 lens4;
    vec4 lens5;
    vec4 lens6;
    vec4 lens7;
} ubuf;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;
    gl_Position = ubuf.qt_Matrix * qt_Vertex;
}
