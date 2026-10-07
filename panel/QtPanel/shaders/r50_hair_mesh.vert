#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 lagOffset;
    vec2 tipTravelPx;
    vec2 nodeOffset1;
    vec2 nodeOffset2;
} ubuf;

layout(binding = 2) uniform sampler2D rootWeight;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;

    // The authority map is zero off-hair, bright at the attachment and dark
    // at the free ends. The exact physics nodes are sampled at three authored
    // strengths, with a smooth zero-velocity join between each segment.
    float rootStrength = texture(rootWeight, qt_MultiTexCoord0).r;
    float occupied = step(0.5 / 255.0, rootStrength);
    const float rootCutoff = 0.42;
    const float midStrength = 74.0 / 255.0;
    const float lowerStrength = 41.0 / 255.0;
    const float tipStrength = 8.0 / 255.0;

    // Guard one production mesh footprint around the bright attachment. A
    // vertex just outside the literal high-root pixels can otherwise pull a
    // triangle through them even though those high-root vertices are fixed.
    vec2 guardStep = vec2(16.0 / 3840.0, 16.0 / 2160.0);
    float rootGuardStrength = rootStrength;
    rootGuardStrength = max(rootGuardStrength,
        texture(rootWeight, qt_MultiTexCoord0 + vec2( guardStep.x, 0.0)).r);
    rootGuardStrength = max(rootGuardStrength,
        texture(rootWeight, qt_MultiTexCoord0 + vec2(-guardStep.x, 0.0)).r);
    rootGuardStrength = max(rootGuardStrength,
        texture(rootWeight, qt_MultiTexCoord0 + vec2(0.0,  guardStep.y)).r);
    rootGuardStrength = max(rootGuardStrength,
        texture(rootWeight, qt_MultiTexCoord0 + vec2(0.0, -guardStep.y)).r);
    rootGuardStrength = max(rootGuardStrength,
        texture(rootWeight, qt_MultiTexCoord0 + guardStep).r);
    rootGuardStrength = max(rootGuardStrength,
        texture(rootWeight, qt_MultiTexCoord0 - guardStep).r);
    rootGuardStrength = max(rootGuardStrength,
        texture(rootWeight, qt_MultiTexCoord0 + vec2(guardStep.x, -guardStep.y)).r);
    rootGuardStrength = max(rootGuardStrength,
        texture(rootWeight, qt_MultiTexCoord0 + vec2(-guardStep.x, guardStep.y)).r);

    vec2 midNode = clamp(ubuf.nodeOffset1, vec2(-1.0), vec2(1.0));
    vec2 lowerNode = clamp(ubuf.nodeOffset2, vec2(-1.0), vec2(1.0));
    vec2 tipNode = clamp(ubuf.lagOffset, vec2(-1.0), vec2(1.0));
    vec2 nodeDisplacement;
    if (rootStrength >= midStrength) {
        float blend = 1.0 - smoothstep(midStrength, rootCutoff, rootStrength);
        nodeDisplacement = mix(vec2(0.0), midNode, blend);
    } else if (rootStrength >= lowerStrength) {
        float blend = 1.0 - smoothstep(lowerStrength, midStrength, rootStrength);
        nodeDisplacement = mix(midNode, lowerNode, blend);
    } else {
        float blend = 1.0 - smoothstep(tipStrength, lowerStrength, rootStrength);
        nodeDisplacement = mix(lowerNode, tipNode, blend);
    }

    // Exactly pin the root threshold and empty canvas. Every moving segment
    // remains a convex blend of clamped nodes, so it cannot exceed tip travel.
    float movable = occupied * (1.0 - step(rootCutoff, rootGuardStrength));
    vec2 safeTravel = max(ubuf.tipTravelPx, vec2(0.0));

    // qt_Vertex is in ShaderEffect item pixels. Moving vertices while keeping
    // UVs unchanged bends the cutout instead of sliding the whole texture.
    vec4 displaced = qt_Vertex;
    displaced.xy += movable * nodeDisplacement * safeTravel;
    gl_Position = ubuf.qt_Matrix * displaced;
}
